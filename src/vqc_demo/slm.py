"""Phase-only SLM hologram export — the garage-to-lab handoff.

This is the *coherent* path. The projector MP4 is intensity-only marketing
and decoder validation. These phase maps are what a bench with laser +
phase-only SLM + Fourier lens can actually load.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from .codec import Quaternion, encode_shard, encode_shard_atlas, payload_to_bytes
from .lg import lg_mode

SLM_PRESETS: dict[str, dict] = {
    "generic_512": {
        "name": "generic_512",
        "width": 512,
        "height": 512,
        "pitch_um": 8.0,
        "wavelength_nm": 1550.0,
        "bit_depth": 8,
        "notes": "Algorithm validation grid.",
    },
    "holoeye_pluto_2": {
        "name": "holoeye_pluto_2",
        "width": 1920,
        "height": 1080,
        "pitch_um": 8.0,
        "wavelength_nm": 1550.0,
        "bit_depth": 8,
        "notes": "Holoeye PLUTO-2 class. Upload 8-bit BMP/PNG.",
    },
    "thorlabs_1080p": {
        "name": "thorlabs_1080p",
        "width": 1920,
        "height": 1080,
        "pitch_um": 6.4,
        "wavelength_nm": 633.0,
        "bit_depth": 8,
        "notes": "Visible HeNe demo on a 1080p LCOS.",
    },
}


@dataclass
class SLMConfig:
    name: str = "generic_512"
    width: int = 512
    height: int = 512
    pitch_um: float = 8.0
    wavelength_nm: float = 1550.0
    bit_depth: int = 8
    extent_mm: float = 4.0
    w0_mm: float = 0.8
    notes: str = ""

    @classmethod
    def from_preset(cls, name: str, extent_mm: float = 4.0) -> SLMConfig:
        if name not in SLM_PRESETS:
            known = ", ".join(sorted(SLM_PRESETS))
            raise KeyError(f"unknown SLM preset {name!r}; choose one of: {known}")
        p = SLM_PRESETS[name]
        return cls(
            name=p["name"],
            width=int(p["width"]),
            height=int(p["height"]),
            pitch_um=float(p["pitch_um"]),
            wavelength_nm=float(p["wavelength_nm"]),
            bit_depth=int(p["bit_depth"]),
            extent_mm=extent_mm,
            notes=str(p.get("notes") or ""),
        )


def _grid(cfg: SLMConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    half = cfg.extent_mm / 2.0
    x = np.linspace(-half, half, cfg.width)
    y = np.linspace(-half, half, cfg.height)
    X, Y = np.meshgrid(x, y)
    return X, Y, np.hypot(X, Y), np.arctan2(Y, X)


def nested_lg_field(
    rho: np.ndarray,
    phi: np.ndarray,
    w0: float,
    ells: list[int],
    amplitudes: list[float],
    quat_phase: float = 0.0,
) -> np.ndarray:
    """Superpose PWM-gated LG modes — the coherent sibling of the RGB donuts."""
    field = np.zeros_like(rho, dtype=np.complex128)
    for ell, amp in zip(ells, amplitudes):
        if amp <= 0:
            continue
        field += amp * lg_mode(ell, rho, phi, w0=w0)
    return field * np.exp(1j * quat_phase)


def gerchberg_saxton(target_amp: np.ndarray, n_iter: int = 24, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    target = target_amp / (float(target_amp.max()) + 1e-12)
    phase = rng.uniform(0.0, 2 * np.pi, target.shape)
    for _ in range(n_iter):
        far = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(np.exp(1j * phase))))
        far = target * np.exp(1j * np.angle(far))
        slm = np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(far)))
        phase = np.mod(np.angle(slm), 2 * np.pi)
    return phase


def phase_to_levels(phase: np.ndarray, bit_depth: int = 8) -> np.ndarray:
    norm = np.mod(phase, 2 * np.pi) / (2 * np.pi)
    max_val = (1 << bit_depth) - 1
    return np.round(norm * max_val).astype(np.uint16 if bit_depth > 8 else np.uint8)


def _duties_from_payload(data: bytes, n_orbs: int = 4) -> list[float]:
    if not data:
        return [0.5] * n_orbs
    return [0.25 + 0.5 * (data[i % len(data)] / 255.0) for i in range(n_orbs)]


def phase_sequence(
    payload: str | bytes,
    cfg: SLMConfig,
    *,
    num_frames: int = 16,
    n_orbs: int = 4,
    use_gs: bool = False,
    gs_iter: int = 16,
) -> tuple[np.ndarray, dict]:
    data = payload_to_bytes(payload)
    q, atlas_i = encode_shard_atlas(data)
    quat_phase = float(q.w * np.pi / 2.0)
    duties = _duties_from_payload(data, n_orbs)
    X, Y, rho, phi = _grid(cfg)
    ells = [1, -1, 2, -2, 3, -3, 4, -4][:n_orbs]
    t = np.linspace(0.0, 1.0, num_frames)
    stack = np.zeros((num_frames, cfg.height, cfg.width), dtype=np.float64)
    for i, ti in enumerate(t):
        amps = []
        for k, duty in enumerate(duties):
            # PWM gate over the sequence — Orbital Braille in time.
            on = (np.sin(2 * np.pi * (1.0 + 0.3 * k) * ti) + 1.0) / 2.0 < duty
            amps.append(1.0 if on else 0.12)
        field = nested_lg_field(rho, phi, cfg.w0_mm, ells, amps, quat_phase=quat_phase)
        if use_gs:
            stack[i] = gerchberg_saxton(np.abs(field), n_iter=gs_iter, seed=i)
        else:
            stack[i] = np.mod(np.angle(field), 2 * np.pi)
    meta = {
        "payload_text": data.decode("utf-8", errors="replace"),
        "payload_hex": data.hex(),
        "quaternion": list(q.as_tuple()),
        "atlas_index": atlas_i,
        "atlas_size": 24,
        "num_orbs": n_orbs,
        "ells": ells,
        "pwm_duties": duties,
        "frames": num_frames,
        "device": asdict(cfg),
        "gerchberg_saxton": use_gs,
        "disclaimer": (
            "These are coherent phase maps for a phase-only SLM. "
            "They are not the projector MP4. A lamp-based SXRD cannot play them."
        ),
    }
    return stack, meta


def export_hologram_package(
    payload: str | bytes,
    out_dir: str | Path,
    *,
    preset: str = "generic_512",
    num_frames: int = 16,
    n_orbs: int = 4,
    use_gs: bool = False,
    gs_iter: int = 16,
    export_raw: bool = True,
) -> dict:
    cfg = SLMConfig.from_preset(preset)
    out = Path(out_dir)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    stack, meta = phase_sequence(
        payload, cfg, num_frames=num_frames, n_orbs=n_orbs, use_gs=use_gs, gs_iter=gs_iter
    )
    meta["created_utc"] = datetime.now(timezone.utc).isoformat()
    meta["generator"] = "vqc_demo.slm.export_hologram_package"

    ext = "png" if cfg.bit_depth <= 8 else "tiff"
    for i, phase in enumerate(stack):
        levels = phase_to_levels(phase, cfg.bit_depth)
        path = frames_dir / f"phase_{i:04d}.{ext}"
        if cfg.bit_depth > 8:
            Image.fromarray(levels, mode="I;16").save(path)
        else:
            Image.fromarray(levels, mode="L").save(path)
        if export_raw:
            (frames_dir / f"phase_{i:04d}.raw").write_bytes(levels.tobytes())

    np.save(out / "phase_stack.npy", stack)
    (out / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _write_lut(out / "LUT_calibration.txt", cfg)
    _write_bench_readme(out / "README.txt", cfg, meta)
    _write_preview(stack, out / "preview_montage.png")
    meta["out_dir"] = str(out)
    meta["n_phase_frames"] = int(stack.shape[0])
    return meta


def _write_preview(stack: np.ndarray, path: Path, max_frames: int = 8) -> None:
    n = min(max_frames, stack.shape[0])
    tiles = [phase_to_levels(stack[i], 8) for i in range(n)]
    h, w = tiles[0].shape
    cols = min(4, n)
    rows = int(np.ceil(n / cols))
    sheet = np.zeros((rows * h, cols * w), dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * h : (r + 1) * h, c * w : (c + 1) * w] = tile
    Image.fromarray(sheet, mode="L").save(path)


def _write_lut(path: Path, cfg: SLMConfig) -> None:
    path.write_text(
        f"VQC demo SLM LUT — linear 0..2π → 0..{ (1 << cfg.bit_depth) - 1 }\n"
        f"device={cfg.name}  {cfg.width}x{cfg.height}  pitch={cfg.pitch_um} um\n"
        f"wavelength={cfg.wavelength_nm} nm  bits={cfg.bit_depth}\n"
        "Calibrate with the vendor LUT if the panel is not linear in phase.\n"
        "Do not upload projector MP4 frames to the SLM.\n",
        encoding="utf-8",
    )


def _write_bench_readme(path: Path, cfg: SLMConfig, meta: dict) -> None:
    path.write_text(
        "VQC SLM hologram package\n"
        "========================\n\n"
        "This folder is the garage-to-lab handoff. Load frames/phase_XXXX.png\n"
        "(or .raw) onto a phase-only SLM. A lamp projector cannot play these.\n\n"
        f"Device preset : {cfg.name} ({cfg.width}x{cfg.height})\n"
        f"Wavelength    : {cfg.wavelength_nm} nm\n"
        f"Payload       : {meta.get('payload_text')!r}\n"
        f"Atlas vertex  : {meta.get('atlas_index')} / 24\n"
        f"Orbs / ells   : {meta.get('num_orbs')} / {meta.get('ells')}\n\n"
        "Suggested bench\n"
        "  laser → beam expander → phase-only SLM → Fourier lens → camera\n"
        "  optional: helical grating or ℓ-sorter after the lens\n\n"
        "What you should see\n"
        "  Nested donut (LG carrier) with 2–4 PWM-gated lobes that evolve\n"
        "  across the frame sequence. Not a movie of the projector POC.\n\n"
        "Files\n"
        "  frames/phase_XXXX.png  8-bit (or 16-bit TIFF) phase maps\n"
        "  frames/phase_XXXX.raw  little-endian gray levels\n"
        "  phase_stack.npy        float radians [N,H,W]\n"
        "  manifest.json          payload, quaternion, duties, device\n"
        "  LUT_calibration.txt    linear 0–2π mapping\n",
        encoding="utf-8",
    )
