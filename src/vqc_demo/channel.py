"""Software capture models — intensity proxies, not physical OAM turbulence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
from PIL import Image, ImageFilter


@dataclass
class ChannelModel:
    """
    Projector/camera stand-in.

    ``kolmogorov_r0`` and ``bmgl_gamma`` are *intensity* proxies. They do not
    evolve a coherent wavefront. Use them to stress the decoder, not to claim
    a free-space OAM BER.
    """

    blur_sigma: float = 1.4
    noise_std: float = 0.025
    gamma: float = 2.0
    shift_px: int = 3
    scale: float = 0.97
    seed: int = 0
    # Log-normal scintillation strength (0 = off). ~0.15 is a mild night path.
    kolmogorov_r0: float = 0.0
    # p-wave BMGL-style |sin φ| intensity inhibition (0 = off).
    bmgl_gamma: float = 0.0
    name: str = "custom"

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
            arr = np.clip(arr, 0.0, 1.0) ** (1.0 / self.gamma)
        if self.kolmogorov_r0 > 0:
            arr = arr * _lognormal_scintillation(arr.shape[:2], self.kolmogorov_r0, rng)[..., None]
        if self.bmgl_gamma > 0:
            arr = arr * _bmgl_inhibition(arr.shape[:2], self.bmgl_gamma)[..., None]
        if self.noise_std > 0:
            arr = arr + rng.normal(0.0, self.noise_std, arr.shape).astype(np.float32)
        return (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)

    def to_dict(self) -> dict:
        return asdict(self)

    def with_seed(self, seed: int) -> ChannelModel:
        return replace(self, seed=seed)


def _lognormal_scintillation(hw: tuple[int, int], r0: float, rng: np.random.Generator) -> np.ndarray:
    """Kolmogorov-ish log-normal intensity screen (FFT, −11/3 PSD)."""
    h, w = hw
    ky = np.fft.fftfreq(h)
    kx = np.fft.fftfreq(w)
    kx, ky = np.meshgrid(kx, ky)
    k = np.hypot(kx, ky)
    k[0, 0] = 1.0
    psd = np.power(k, -11.0 / 6.0)  # amplitude ~ sqrt of I(k) ~ k^{-11/3}
    noise = rng.normal(size=(h, w)) + 1j * rng.normal(size=(h, w))
    screen = np.fft.ifft2(noise * psd).real
    screen = screen - screen.mean()
    std = float(screen.std()) or 1.0
    chi = (r0 * screen / std).astype(np.float32)
    field = np.exp(chi)
    return (field / (float(field.mean()) or 1.0)).astype(np.float32)


def _bmgl_inhibition(hw: tuple[int, int], gamma: float) -> np.ndarray:
    """Angular |sin φ| intensity gate — a cartoon of p-wave BMGL, not the PDE."""
    h, w = hw
    yy = np.arange(h, dtype=np.float32) - (h - 1) / 2.0
    xx = np.arange(w, dtype=np.float32) - (w - 1) / 2.0
    phi = np.arctan2(yy[:, None], xx[None, :])
    # Inhibition in the odd-parity lobes; never amplify.
    return (1.0 / (1.0 + gamma * np.abs(np.sin(phi)))).astype(np.float32)


PRESETS: dict[str, ChannelModel] = {
    "clean": ChannelModel(
        name="clean",
        blur_sigma=0.0,
        noise_std=0.0,
        gamma=1.0,
        shift_px=0,
        scale=1.0,
        kolmogorov_r0=0.0,
        bmgl_gamma=0.0,
    ),
    "projector": ChannelModel(
        name="projector",
        blur_sigma=0.4,
        noise_std=0.008,
        gamma=1.3,
        shift_px=0,
        scale=0.995,
    ),
    "harsh": ChannelModel(
        name="harsh",
        blur_sigma=1.4,
        noise_std=0.025,
        gamma=2.0,
        shift_px=2,
        scale=0.97,
    ),
    "kolmogorov": ChannelModel(
        name="kolmogorov",
        blur_sigma=0.6,
        noise_std=0.012,
        gamma=1.4,
        shift_px=1,
        scale=0.98,
        kolmogorov_r0=0.18,
    ),
    "bmgl": ChannelModel(
        name="bmgl",
        blur_sigma=0.5,
        noise_std=0.010,
        gamma=1.3,
        shift_px=0,
        scale=0.99,
        bmgl_gamma=0.8,
    ),
}


def get_preset(name: str) -> ChannelModel:
    if name not in PRESETS:
        known = ", ".join(sorted(PRESETS))
        raise KeyError(f"unknown channel preset {name!r}; choose one of: {known}")
    return PRESETS[name]
