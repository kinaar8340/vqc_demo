"""Recover payload bytes from captured intensity-proxy frames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .codec import Quaternion, bits_to_byte, majority_byte, unpack_packet
from .fidelity import build_report, qec_disagreement
from .lg import bit_radii
from .projector import ProjectorProfile, VPL_HW20A


@dataclass
class DecodeResult:
    payload: bytes
    text: str
    symbols: list[int]
    meta: dict
    crc_ok: bool

    def __str__(self) -> str:
        preview = self.text if self.text.isprintable() else self.payload.hex()
        return f"DecodeResult(crc_ok={self.crc_ok}, n={len(self.payload)}, text={preview!r})"


def load_frame(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def load_frames(paths: list[Path]) -> list[np.ndarray]:
    return [load_frame(p) for p in paths]


def _luminance(frame: np.ndarray) -> np.ndarray:
    rgb = frame.astype(np.float32) / 255.0
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _footer_rows(height: int) -> int:
    """Match FrameRenderer footer: max(18, H//48) plus a small pad."""
    return min(height // 4, max(18, height // 48) + 4)


def _pulse_rows(height: int) -> int:
    """Match FrameRenderer pyramidal pulse bar: max(3, H//64)."""
    return max(3, height // 64) + 2


def _blank_chrome(arr: np.ndarray) -> np.ndarray:
    """Zero the pulse bar and footer so they cannot steal the centroid."""
    out = arr.copy()
    h = out.shape[0]
    out[: _pulse_rows(h)] = 0
    out[h - _footer_rows(h) :] = 0
    return out


def find_center(frame: np.ndarray) -> tuple[float, float]:
    """Intensity centroid, ignoring pulse bar and footer."""
    lum = _blank_chrome(_luminance(frame))
    h, w = lum.shape
    # Soft-threshold so the dark guide rings don't dominate.
    floor = np.percentile(lum, 70)
    weight = np.clip(lum - floor, 0, None)
    if float(weight.sum()) < 1e-6:
        return ((h - 1) / 2.0, (w - 1) / 2.0)
    ys, xs = np.indices(weight.shape)
    cy = float((ys * weight).sum() / weight.sum())
    cx = float((xs * weight).sum() / weight.sum())
    return cy, cx


def _annulus_width(radii: list[float]) -> float:
    return max(2.0, 0.28 * (radii[1] - radii[0] if len(radii) > 1 else radii[0] * 0.2))


def radial_samples(
    lum: np.ndarray,
    cy: float,
    cx: float,
    radii: list[float],
    annulus: float,
) -> np.ndarray:
    """Mean luminance in a thin annulus around each expected peak radius."""
    yy, xx = np.indices(lum.shape, dtype=np.float32)
    rho = np.hypot(xx - cx, yy - cy)
    samples = np.empty(len(radii), dtype=np.float32)
    for i, r in enumerate(radii):
        mask = np.abs(rho - r) <= annulus
        # 85th percentile survives a ring that is clipped by the footer/pulse bar.
        samples[i] = float(np.percentile(lum[mask], 85)) if mask.any() else 0.0
    return samples


def rgb_ring_samples(
    frame: np.ndarray,
    cy: float,
    cx: float,
    radii: list[float],
) -> np.ndarray:
    """Mean RGB in each ring annulus. Shape (n_rings, 3)."""
    rgb = _blank_chrome(frame.astype(np.float32) / 255.0)
    yy, xx = np.indices(rgb.shape[:2], dtype=np.float32)
    rho = np.hypot(xx - cx, yy - cy)
    annulus = _annulus_width(radii)
    out = np.zeros((len(radii), 3), dtype=np.float32)
    for i, r in enumerate(radii):
        mask = np.abs(rho - r) <= annulus
        if mask.any():
            out[i] = rgb[mask].mean(axis=0)
    return out


def estimate_color_mix(calib: np.ndarray) -> np.ndarray:
    """
    3×3 projector→camera mix from the CALIB RGB patches (bottom-left).

    Columns are the measured (R,G,B) of the red, green, and blue squares.
    Inverting this is the POC stand-in for ICA / DWDM demultiplex.
    """
    h, w = calib.shape[:2]
    rgb = calib.astype(np.float32) / 255.0
    pw, ph = max(40, w // 24), max(24, h // 28)
    y1 = h - ph - 16
    cols = []
    for i in range(3):
        x1 = 16 + i * (pw + 10)
        inset = max(2, pw // 6)
        patch = rgb[y1 + inset : y1 + ph - inset, x1 + inset : x1 + pw - inset]
        if patch.size == 0:
            cols.append(np.eye(3, dtype=np.float32)[:, i])
        else:
            cols.append(patch.reshape(-1, 3).mean(axis=0))
    mix = np.stack(cols, axis=1).astype(np.float32)
    # Guard a degenerate capture (e.g. clipped / missing patches).
    if float(np.linalg.cond(mix)) > 50 or float(np.linalg.det(mix)) == 0:
        return np.eye(3, dtype=np.float32)
    return mix


def demix_rgb(samples: np.ndarray, mix: np.ndarray) -> np.ndarray:
    """Apply inv(mix) to each ring's RGB row."""
    try:
        inv = np.linalg.inv(mix)
    except np.linalg.LinAlgError:
        inv = np.eye(3, dtype=np.float32)
    return samples @ inv.T


def recover_quaternion_spoke(
    frame: np.ndarray,
    cy: float,
    cx: float,
    r_max: float,
) -> Quaternion:
    """Estimate the gold spoke as a unit quaternion in the xy plane."""
    lum = _blank_chrome(_luminance(frame))
    yy, xx = np.indices(lum.shape, dtype=np.float32)
    dx, dy = xx - cx, yy - cy
    rho = np.hypot(dx, dy)
    phi = np.arctan2(dy, dx)
    mask = (rho > 0.12 * r_max) & (rho < 0.72 * r_max)
    n_bins = 72
    bins = ((phi + np.pi) / (2 * np.pi) * n_bins).astype(int) % n_bins
    energy = np.zeros(n_bins, dtype=np.float64)
    for b in range(n_bins):
        m = mask & (bins == b)
        if m.any():
            energy[b] = float(lum[m].mean())
    k = int(np.argmax(energy))
    angle = (k + 0.5) / n_bins * 2 * np.pi - np.pi
    contrast = float(energy.max() - np.median(energy))
    # w encodes spoke contrast; z is left at 0 (length is a weak cue here).
    w = float(np.clip(0.4 + 1.2 * contrast, 0.2, 0.95))
    return Quaternion(w, np.cos(angle), np.sin(angle), 0.0).unit()


def decode_symbol(
    frame: np.ndarray,
    radii: list[float],
    cy: float | None = None,
    cx: float | None = None,
) -> int:
    if cy is None or cx is None:
        cy, cx = find_center(frame)
    lum = _blank_chrome(_luminance(frame))
    samples = radial_samples(lum, cy, cx, radii, _annulus_width(radii))
    lo, hi = float(samples.min()), float(samples.max())
    # Guide rings sit ~0.04, ON rings >= ~0.55. A min/max-relative
    # threshold misfires when every ring is ON (0xFF).
    if hi < 0.12:
        return 0
    if lo > 0.40:
        return 0xFF
    bits = (samples >= 0.30).astype(np.uint8)
    return bits_to_byte(bits)


def group_held_frames(frames: list[np.ndarray], hold: int) -> list[list[np.ndarray]]:
    if hold <= 1:
        return [[f] for f in frames]
    groups: list[list[np.ndarray]] = []
    for i in range(0, len(frames), hold):
        chunk = frames[i : i + hold]
        if chunk:
            groups.append(chunk)
    return groups


def expected_radii(profile: ProjectorProfile, n_rings: int, w0_frac: float) -> list[float]:
    del w0_frac  # radii are linear; kept so call sites stay stable
    return bit_radii(n_rings, profile.short_axis, profile.safe_area)


def decode_frames(
    frames: list[np.ndarray],
    *,
    profile: ProjectorProfile | None = None,
    hold_frames: int | None = None,
    n_rings: int = 8,
    w0_frac: float = 0.40,
    qec_reps: int = 3,
    expected: bytes | None = None,
) -> DecodeResult:
    profile = profile or VPL_HW20A
    hold = hold_frames if hold_frames is not None else profile.hold_frames
    radii = expected_radii(profile, n_rings, w0_frac)

    # Center from the brightest non-black frame (usually first data/calib).
    centers = [find_center(f) for f in frames[:: max(1, len(frames) // 8)] or frames[:1]]
    cy = float(np.median([c[0] for c in centers]))
    cx = float(np.median([c[1] for c in centers]))

    symbols: list[int] = []
    disagreements: list[float] = []
    snr_acc: list[float] = []
    rgb_stack: list[np.ndarray] = []
    mix = estimate_color_mix(frames[0]) if frames else np.eye(3, dtype=np.float32)

    for group in group_held_frames(frames, hold):
        votes = [decode_symbol(f, radii, cy, cx) for f in group]
        # Skip near-black groups (calib/black) — they decode as 0.
        lum = float(np.mean([_luminance(f).mean() for f in group]))
        if lum < 0.045 and all(v == 0 for v in votes):
            continue
        symbols.append(majority_byte(votes))
        disagreements.append(qec_disagreement(votes))
        mid = group[len(group) // 2]
        rgb = rgb_ring_samples(mid, cy, cx, radii)
        rgb_stack.append(demix_rgb(rgb, mix))
        samples = radial_samples(
            _luminance(mid), cy, cx, radii, _annulus_width(radii)
        )
        noise = float(np.median(samples)) + 1e-6
        peak = float(samples.max())
        snr_acc.append(20.0 * float(np.log10(max(peak, 1e-6) / noise)))

    payload, meta = unpack_packet(symbols, qec_reps=qec_reps)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = ""

    quat = None
    data_frames = [g[0] for g in group_held_frames(frames, hold) if _luminance(g[0]).mean() > 0.05]
    if data_frames:
        quat = recover_quaternion_spoke(data_frames[len(data_frames) // 2], cy, cx, radii[-1])

    meta["center"] = (cy, cx)
    meta["n_raw_symbols"] = len(symbols)
    meta["color_mix"] = mix.tolist()
    meta["quaternion"] = list(quat.as_tuple()) if quat else None
    meta["report"] = build_report(
        payload=payload,
        text=text,
        crc_ok=True,
        expected=expected,
        qec_disagree_mean=float(np.mean(disagreements)) if disagreements else 0.0,
        ring_snr_db=float(np.mean(snr_acc)) if snr_acc else None,
        quat=quat,
        extra={"n_demixed_shards": len(rgb_stack)},
    )
    return DecodeResult(
        payload=payload,
        text=text,
        symbols=symbols,
        meta=meta,
        crc_ok=True,
    )


def decode_png_dir(
    frames_dir: Path,
    glob: str = "frame_*.png",
    **kwargs,
) -> DecodeResult:
    paths = sorted(frames_dir.glob(glob))
    if not paths:
        # captured name
        paths = sorted(frames_dir.glob("cap_*.png"))
    if not paths:
        raise FileNotFoundError(f"no PNG frames in {frames_dir}")
    return decode_frames(load_frames(paths), **kwargs)
