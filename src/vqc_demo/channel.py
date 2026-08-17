"""Software capture model: blur, gamma, shift, noise (not physical OAM)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


@dataclass
class ChannelModel:
    blur_sigma: float = 1.4
    noise_std: float = 0.025
    gamma: float = 2.0
    shift_px: int = 3
    scale: float = 0.97
    seed: int = 0

    def apply(self, frame: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        img = Image.fromarray(frame, mode="RGB")
        if self.scale != 1.0:
            w, h = img.size
            nw, nh = max(8, int(w * self.scale)), max(8, int(h * self.scale))
            img = img.resize((nw, nh), Image.Resampling.BILINEAR).resize(
                (w, h), Image.Resampling.BILINEAR
            )
        if self.blur_sigma > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=self.blur_sigma))
        arr = np.asarray(img).astype(np.float32) / 255.0
        if self.shift_px:
            sy = int(rng.integers(-self.shift_px, self.shift_px + 1))
            sx = int(rng.integers(-self.shift_px, self.shift_px + 1))
            arr = np.roll(np.roll(arr, sy, axis=0), sx, axis=1)
        if self.gamma and self.gamma != 1.0:
            # Projector ~2.2 encode, camera decode — leftover mismatch.
            arr = np.clip(arr, 0.0, 1.0) ** (1.0 / self.gamma)
        if self.noise_std > 0:
            arr = arr + rng.normal(0.0, self.noise_std, arr.shape).astype(np.float32)
        return (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
