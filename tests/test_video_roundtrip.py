import shutil
from pathlib import Path

import pytest

from vqc_demo.decoder import decode_png_dir
from vqc_demo.pipeline import encode_to_dir
from vqc_demo.projector import TEST_PROFILE

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _cfg():
    return {
        "encode": {
            "qec_reps": 3,
            "n_rings": 8,
            "guide_level": 0.08,
            "on_level": 1.0,
            "payload_max": 256,
            "version": 1,
        },
        "optics": {"w0_frac": 0.40, "p": 0},
        "paths": {
            "frames_subdir": "frames",
            "video_name": "vqc_poc.mp4",
            "manifest_name": "manifest.json",
        },
    }


def test_ffmpeg_encode_decode(tmp_path: Path):
    result = encode_to_dir(
        "I live in Oregon",
        tmp_path,
        profile=TEST_PROFILE,
        cfg=_cfg(),
        stitch=True,
    )
    assert result.video_path is not None and result.video_path.is_file()
    decoded = decode_png_dir(
        result.frames_dir,
        profile=TEST_PROFILE,
        hold_frames=TEST_PROFILE.hold_frames,
    )
    assert decoded.payload == b"I live in Oregon"
