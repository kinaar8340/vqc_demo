"""Laguerre-Gaussian p=0 intensity donuts (RGB-proxy, not coherent OAM)."""

from __future__ import annotations

import numpy as np
from scipy.special import factorial, genlaguerre


def lg_mode(ell: int, rho: np.ndarray, phi: np.ndarray, w0: float, p: int = 0) -> np.ndarray:
    """Complex LG field: radial envelope × exp(i ℓ φ). For SLM phase export."""
    return lg_radial(p, ell, rho, w0) * np.exp(1j * int(ell) * phi)


def lg_radial(p: int, ell: int, rho: np.ndarray, w0: float) -> np.ndarray:
    """Radial LG_{p}^{|ell|} envelope."""
    L = abs(int(ell))
    norm = np.sqrt(2.0 * factorial(L) / (np.pi * w0**2 * factorial(p)))
    rw = np.sqrt(2.0) * rho / w0
    lag = genlaguerre(p, L)(rw**2)
    return norm * (rw**L) * np.exp(-(rw**2) / 2.0) * lag


def peak_radius(ell: int, w0: float, p: int = 0) -> float:
    """
    Intensity peak radius for LG_{p=0}^{|ell|}.

    For p=0 the envelope peaks at rho = w0 * sqrt(|ell| / 2).
    """
    if p != 0:
        raise NotImplementedError("peak_radius is closed-form only for p=0")
    L = abs(int(ell))
    if L == 0:
        return 0.0
    return float(w0 * np.sqrt(L / 2.0))


def lg_intensity_map(
    ell: int,
    height: int,
    width: int,
    w0: float,
    p: int = 0,
) -> np.ndarray:
    """Normalized |LG|^2 on a pixel grid centered in the frame."""
    yy = np.arange(height, dtype=np.float64) - (height - 1) / 2.0
    xx = np.arange(width, dtype=np.float64) - (width - 1) / 2.0
    X, Y = np.meshgrid(xx, yy)
    rho = np.hypot(X, Y)
    field = lg_radial(p, ell, rho, w0)
    inten = field**2
    peak = float(inten.max())
    if peak > 0:
        inten = inten / peak
    return inten.astype(np.float32)


def precompute_rings(
    n_rings: int,
    height: int,
    width: int,
    w0: float,
    p: int = 0,
) -> list[np.ndarray]:
    """Return n_rings intensity maps for |ell| = 1 .. n_rings."""
    return [lg_intensity_map(ell, height, width, w0, p=p) for ell in range(1, n_rings + 1)]


def choose_w0(short_axis: int, safe_area: float, max_ell: int, w0_frac: float) -> float:
    """Pick w0 so the outermost ring peak stays inside the safe area."""
    half = 0.5 * short_axis * safe_area
    # peak(|ell|=max) = w0 * sqrt(max_ell / 2) == half * w0_frac
    # so w0 = half * w0_frac / sqrt(max_ell / 2)
    return float(half * w0_frac / np.sqrt(max_ell / 2.0))


def bit_radii(
    n_rings: int,
    short_axis: int,
    safe_area: float,
    inner_frac: float = 0.22,
    outer_frac: float = 0.80,
) -> list[float]:
    """
    Evenly spaced radii for the 8-bit ring barcode.

    True LG peaks bunch up as sqrt(|ℓ|) and the p=0 envelopes are wide, so
    sampling those peaks crosstalks. Linear spacing leaves a camera-safe gap
    while the rings still read as nested donuts.
    """
    half = 0.5 * float(short_axis) * safe_area
    return [float(r) for r in np.linspace(inner_frac * half, outer_frac * half, n_rings)]


def annulus_map(
    height: int,
    width: int,
    radius: float,
    sigma: float,
) -> np.ndarray:
    """Unit-peak Gaussian annulus on a pixel grid."""
    yy = np.arange(height, dtype=np.float64) - (height - 1) / 2.0
    xx = np.arange(width, dtype=np.float64) - (width - 1) / 2.0
    rho = np.hypot(*np.meshgrid(xx, yy))
    sigma = max(float(sigma), 0.75)
    inten = np.exp(-0.5 * ((rho - radius) / sigma) ** 2)
    peak = float(inten.max())
    if peak > 0:
        inten = inten / peak
    return inten.astype(np.float32)


def precompute_annuli(
    radii: list[float],
    height: int,
    width: int,
    sigma_frac: float = 0.22,
) -> list[np.ndarray]:
    """Narrow annulus maps; sigma is a fraction of the minimum ring gap."""
    if len(radii) >= 2:
        gap = min(radii[i + 1] - radii[i] for i in range(len(radii) - 1))
    else:
        gap = radii[0] * 0.25 if radii else 4.0
    sigma = max(0.75, sigma_frac * gap)
    return [annulus_map(height, width, r, sigma) for r in radii]
