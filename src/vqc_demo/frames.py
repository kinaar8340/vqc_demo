"""Render 1080p (or test-size) intensity-proxy frames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .codec import Quaternion, byte_to_bits
from .lg import bit_radii, choose_w0, precompute_annuli, precompute_rings
from .projector import ProjectorProfile, VPL_HW20A

# Per-ℓ DWDM proxy palette (visible-light stand-in for wavelength shards).
DWDM = np.array(
    [
        [1.00, 0.22, 0.18],  # ℓ=1  red
        [1.00, 0.52, 0.10],  # ℓ=2  amber
        [1.00, 0.84, 0.22],  # ℓ=3  gold
        [0.28, 1.00, 0.32],  # ℓ=4  green
        [0.16, 0.92, 0.88],  # ℓ=5  cyan
        [0.30, 0.42, 1.00],  # ℓ=6  blue
        [0.72, 0.28, 1.00],  # ℓ=7  violet
        [1.00, 0.38, 0.68],  # ℓ=8  magenta
    ],
    dtype=np.float32,
)
GUIDE = np.array([0.22, 0.22, 0.26], dtype=np.float32)
BG = np.array([0.02, 0.02, 0.04], dtype=np.float32)
SPOKE = np.array([1.00, 0.70, 0.10], dtype=np.float32)
GOLD = DWDM[2]


@dataclass
class RenderConfig:
    n_rings: int = 8
    guide_level: float = 0.08
    on_level: float = 1.0
    w0_frac: float = 0.40
    p: int = 0
    lg_underlay: float = 0.05
    pulse_bar: bool = True


class FrameRenderer:
    def __init__(
        self,
        profile: ProjectorProfile | None = None,
        render: RenderConfig | None = None,
    ) -> None:
        self.profile = profile or VPL_HW20A
        self.render = render or RenderConfig()
        self.w0 = choose_w0(
            self.profile.short_axis,
            self.profile.safe_area,
            self.render.n_rings,
            self.render.w0_frac,
        )
        self.peak_radii = bit_radii(
            self.render.n_rings,
            self.profile.short_axis,
            self.profile.safe_area,
        )
        self.rings = precompute_annuli(
            self.peak_radii,
            self.profile.height,
            self.profile.width,
        )
        self.lg_maps: list[np.ndarray] = []
        if self.render.lg_underlay > 0:
            self.lg_maps = precompute_rings(
                self.render.n_rings,
                self.profile.height,
                self.profile.width,
                self.w0,
                p=self.render.p,
            )
        cy = (self.profile.height - 1) / 2.0
        cx = (self.profile.width - 1) / 2.0
        yy = np.arange(self.profile.height, dtype=np.float32)[:, None] - cy
        xx = np.arange(self.profile.width, dtype=np.float32)[None, :] - cx
        self._phi = np.arctan2(yy, xx)
        self._rho = np.hypot(xx, yy)

    def render_data(
        self,
        symbol: int,
        quat: Quaternion,
        index: int,
        pulse: float = 1.0,
    ) -> np.ndarray:
        bits = byte_to_bits(symbol, self.render.n_rings)
        img = np.broadcast_to(BG, (*self.rings[0].shape, 3)).copy()
        # Faint true-LG wash so the frame reads as nested donuts (patent look).
        if self.lg_maps:
            for i, lg in enumerate(self.lg_maps):
                img += lg[..., None] * DWDM[i % len(DWDM)] * self.render.lg_underlay
        for i, ring in enumerate(self.rings):
            on = bool(bits[i])
            # Mix DWDM hue with gold so every ON ring has similar Rec.709 luma
            # (pure blue/violet would otherwise fall under the bit threshold).
            color = _on_color(i) if on else GUIDE
            level = self.render.on_level if on else self.render.guide_level
            img += ring[..., None] * color * level
        img = self._add_spoke(img, quat)
        if self.render.pulse_bar:
            img = self._add_pulse_bar(img, pulse)
        img = np.clip(img, 0.0, 1.0)
        return self._to_u8(img, label=f"SYM {index:04d}  0x{symbol:02X}")

    def render_calib(self) -> np.ndarray:
        h, w = self.profile.height, self.profile.width
        img = np.broadcast_to(BG, (h, w, 3)).copy()
        cy, cx = h // 2, w // 2
        t = max(2, h // 180)
        img[cy - t : cy + t + 1, :, :] = 0.92
        img[:, cx - t : cx + t + 1, :] = 0.92
        # Corner ticks (overscan / keystone check).
        arm = max(18, w // 40)
        for y0, x0 in ((8, 8), (8, w - 8), (h - 8, 8), (h - 8, w - 8)):
            img[y0 - 1 : y0 + 2, x0 - arm : x0 + arm, :] = 0.85
            img[y0 - arm : y0 + arm, x0 - 1 : x0 + 2, :] = 0.85
        # RGB patches for camera white-balance.
        pw, ph = max(40, w // 24), max(24, h // 28)
        y1 = h - ph - 16
        patches = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        for i, col in enumerate(patches):
            x1 = 16 + i * (pw + 10)
            img[y1 : y1 + ph, x1 : x1 + pw, :] = col
        return self._to_u8(np.clip(img, 0.0, 1.0), label="CALIB")

    def render_black(self, label: str = "BLACK") -> np.ndarray:
        h, w = self.profile.height, self.profile.width
        img = np.broadcast_to(BG, (h, w, 3)).copy()
        return self._to_u8(img, label=label)

    def _add_pulse_bar(self, img: np.ndarray, pulse: float) -> np.ndarray:
        """Pyramidal-FM proxy: a top luminance bar that rises and falls over the packet."""
        h = max(3, self.profile.height // 64)
        level = float(np.clip(pulse, 0.0, 1.0))
        img[:h, :, :] = np.clip(img[:h, :, :] * 0.15 + GOLD * level, 0.0, 1.0)
        return img

    def _add_spoke(self, img: np.ndarray, quat: Quaternion) -> np.ndarray:
        q = quat.unit()
        angle = float(np.arctan2(q.y, q.x))
        # Spoke length encodes |z|; brightness encodes w.
        r_max = self.peak_radii[-1] * (0.55 + 0.45 * abs(q.z))
        half_width = max(1.2, self.profile.short_axis / 400.0)
        # Angular wedge around `angle`.
        dphi = (self._phi - angle + np.pi) % (2 * np.pi) - np.pi
        mask = (np.abs(dphi) < (half_width / np.maximum(self._rho, 1.0))) & (
            self._rho < r_max
        )
        strength = 0.35 + 0.65 * abs(q.w)
        img[mask] = np.clip(img[mask] + SPOKE * strength, 0.0, 1.0)
        return img

    def _to_u8(self, img: np.ndarray, label: str) -> np.ndarray:
        arr = (img * 255.0).astype(np.uint8)
        pil = Image.fromarray(arr, mode="RGB")
        draw = ImageDraw.Draw(pil)
        font = _tiny_font()
        bar_h = max(18, self.profile.height // 48)
        draw.rectangle((0, self.profile.height - bar_h, self.profile.width, self.profile.height), fill=(8, 8, 12))
        text = f"VQC INTENSITY PROXY  ·  {label}  ·  NOT COHERENT OAM  ·  {self.profile.name}"
        draw.text((10, self.profile.height - bar_h + 2), text, fill=(200, 180, 90), font=font)
        return np.asarray(pil)


def _on_color(ring_index: int) -> np.ndarray:
    tint = DWDM[ring_index % len(DWDM)]
    mixed = 0.55 * GOLD + 0.45 * tint
    return np.clip(mixed, 0.0, 1.0).astype(np.float32)


def _tiny_font():
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        return ImageFont.load_default()


def save_png(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame, mode="RGB").save(path, format="PNG", optimize=True)


def write_sequence(
    out_dir: Path,
    frames: list[np.ndarray],
    stem: str = "frame",
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, frame in enumerate(frames):
        p = out_dir / f"{stem}_{i:05d}.png"
        save_png(p, frame)
        paths.append(p)
    return paths


def contact_sheet(frames: list[np.ndarray], cols: int = 4, max_frames: int = 12) -> np.ndarray:
    """Small preview grid of the first few unique frames."""
    take = frames[:max_frames]
    if not take:
        raise ValueError("no frames")
    h, w = take[0].shape[:2]
    thumb_w = 320
    thumb_h = int(h * thumb_w / w)
    cols = min(cols, len(take))
    rows = int(np.ceil(len(take) / cols))
    sheet = np.zeros((rows * thumb_h, cols * thumb_w, 3), dtype=np.uint8)
    for i, fr in enumerate(take):
        im = Image.fromarray(fr).resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
        r, c = divmod(i, cols)
        sheet[r * thumb_h : (r + 1) * thumb_h, c * thumb_w : (c + 1) * thumb_w] = np.asarray(im)
    return sheet
