import numpy as np

from vqc_demo.lg import choose_w0, lg_intensity_map, peak_radius, precompute_rings


def test_peak_radius_scaling():
    w0 = 40.0
    r1 = peak_radius(1, w0)
    r4 = peak_radius(4, w0)
    assert abs(r1 - w0 * np.sqrt(0.5)) < 1e-9
    assert abs(r4 / r1 - 2.0) < 1e-9


def test_intensity_peaks_near_formula():
    w0 = 28.0
    h = w = 161
    ell = 4
    inten = lg_intensity_map(ell, h, w, w0)
    cy = cx = (h - 1) / 2.0
    yy, xx = np.indices(inten.shape)
    rho = np.hypot(xx - cx, yy - cy)
    peak_r = float(rho.ravel()[int(np.argmax(inten))])
    assert abs(peak_r - peak_radius(ell, w0)) < 2.5


def test_w0_keeps_outer_ring_inside_safe_area():
    short = 180
    safe = 0.86
    n = 8
    w0 = choose_w0(short, safe, n, w0_frac=0.40)
    outer = peak_radius(n, w0)
    assert outer < 0.5 * short * safe


def test_precompute_count():
    rings = precompute_rings(8, 64, 80, w0=12.0)
    assert len(rings) == 8
    assert rings[0].shape == (64, 80)
    assert all(r.max() == 1.0 for r in rings)


def test_bit_radii_are_separated():
    from vqc_demo.lg import bit_radii

    radii = bit_radii(8, 180, 0.86)
    gaps = [radii[i + 1] - radii[i] for i in range(7)]
    assert all(g > 6.0 for g in gaps)
    assert radii[-1] < 0.5 * 180 * 0.86 * 0.85
