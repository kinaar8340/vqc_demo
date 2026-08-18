from pathlib import Path

import numpy as np

from vqc_demo.slm import SLMConfig, export_hologram_package, phase_sequence


def test_phase_stack_shape_and_range():
    cfg = SLMConfig.from_preset("generic_512")
    cfg.width = 64
    cfg.height = 48
    stack, meta = phase_sequence("I live in Oregon", cfg, num_frames=4, n_orbs=4)
    assert stack.shape == (4, 48, 64)
    assert stack.min() >= 0.0
    assert stack.max() <= 2 * np.pi + 1e-9
    assert meta["atlas_size"] == 24


def test_export_writes_bench_bundle(tmp_path: Path):
    # Tiny custom preset via monkeypatch of dimensions after from_preset.
    from vqc_demo.slm import SLM_PRESETS

    old = SLM_PRESETS["generic_512"].copy()
    SLM_PRESETS["generic_512"].update({"width": 64, "height": 48})
    try:
        meta = export_hologram_package(
            "VQC",
            tmp_path,
            preset="generic_512",
            num_frames=3,
            n_orbs=2,
        )
    finally:
        SLM_PRESETS["generic_512"] = old
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "phase_stack.npy").is_file()
    assert (tmp_path / "README.txt").is_file()
    assert (tmp_path / "LUT_calibration.txt").is_file()
    assert (tmp_path / "preview_montage.png").is_file()
    assert (tmp_path / "frames" / "phase_0000.png").is_file()
    assert (tmp_path / "frames" / "phase_0000.raw").is_file()
    assert meta["n_phase_frames"] == 3
