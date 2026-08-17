from vqc_demo.channel import ChannelModel
from vqc_demo.pipeline import loopback
from vqc_demo.projector import TEST_PROFILE


def _cfg():
    return {
        "encode": {"qec_reps": 3, "n_rings": 8, "guide_level": 0.08, "on_level": 1.0, "payload_max": 256, "version": 1},
        "optics": {"w0_frac": 0.40, "p": 0},
        "channel": {},
    }


def test_loopback_patent_payload():
    result = loopback("I live in Oregon", profile=TEST_PROFILE, cfg=_cfg())
    assert result.crc_ok
    assert result.payload == b"I live in Oregon"
    assert result.text == "I live in Oregon"


def test_loopback_empty_and_binary():
    empty = loopback(b"", profile=TEST_PROFILE, cfg=_cfg())
    assert empty.payload == b""
    blob = bytes(range(16))
    got = loopback(blob, profile=TEST_PROFILE, cfg=_cfg())
    assert got.payload == blob


def test_loopback_with_capture_model():
    ch = ChannelModel(blur_sigma=0.4, noise_std=0.008, gamma=1.3, shift_px=0, scale=0.995, seed=7)
    result = loopback(
        "VQC",
        profile=TEST_PROFILE,
        cfg=_cfg(),
        channel=ch,
        apply_channel=True,
    )
    assert result.crc_ok
    assert result.payload == b"VQC"
