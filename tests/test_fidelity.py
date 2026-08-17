import numpy as np

from vqc_demo.codec import encode_shard
from vqc_demo.decoder import estimate_color_mix, recover_quaternion_spoke
from vqc_demo.fidelity import hamming_bits, quaternion_error
from vqc_demo.frames import FrameRenderer, RenderConfig
from vqc_demo.pipeline import loopback
from vqc_demo.projector import TEST_PROFILE


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
        "channel": {},
    }


def test_loopback_still_recovers_with_dwdm_and_lg():
    result = loopback("I live in Oregon", profile=TEST_PROFILE, cfg=_cfg())
    assert result.crc_ok
    assert result.payload == b"I live in Oregon"
    report = result.meta["report"]
    assert report["exact_match"] is True
    assert report["ber"] == 0.0
    assert report["qec_disagreement"] == 0.0


def test_calib_color_mix_near_identity():
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig())
    mix = estimate_color_mix(renderer.render_calib())
    assert np.linalg.norm(mix - np.eye(3)) < 0.35


def test_spoke_points_near_encoded_xy():
    payload = b"I live in Oregon"
    expect = encode_shard(payload).unit()
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig())
    frame = renderer.render_data(0xAA, expect, 0, pulse=0.5)
    cy = (TEST_PROFILE.height - 1) / 2.0
    cx = (TEST_PROFILE.width - 1) / 2.0
    got = recover_quaternion_spoke(frame, cy, cx, renderer.peak_radii[-1])
    err = quaternion_error(got, payload)
    assert err is not None
    assert err["spoke_abs_deg"] < 35.0


def test_hamming():
    errs, n = hamming_bits(b"ab", b"ab")
    assert errs == 0 and n == 16
    errs, n = hamming_bits(b"\x00", b"\xff")
    assert errs == 8 and n == 8
