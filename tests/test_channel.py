import numpy as np

from vqc_demo.channel import PRESETS, get_preset


def test_presets_exist():
    for name in ("clean", "projector", "harsh", "kolmogorov", "bmgl"):
        ch = get_preset(name)
        assert ch.name == name


def test_clean_is_identity():
    frame = np.full((32, 48, 3), 120, dtype=np.uint8)
    out = PRESETS["clean"].apply(frame)
    assert out.shape == frame.shape
    assert np.array_equal(out, frame)


def test_kolmogorov_and_bmgl_change_the_frame():
    rng = np.random.default_rng(0)
    frame = (rng.integers(40, 200, size=(64, 80, 3))).astype(np.uint8)
    kol = PRESETS["kolmogorov"].with_seed(1).apply(frame)
    bmgl = PRESETS["bmgl"].with_seed(1).apply(frame)
    assert kol.shape == frame.shape
    assert not np.array_equal(kol, frame)
    assert not np.array_equal(bmgl, frame)
