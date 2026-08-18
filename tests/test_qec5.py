from vqc_demo.codec import pack_packet, unpack_packet
from vqc_demo.pipeline import loopback
from vqc_demo.projector import TEST_PROFILE


def _cfg(reps: int):
    return {
        "encode": {
            "qec_reps": reps,
            "n_rings": 8,
            "guide_level": 0.08,
            "on_level": 1.0,
            "payload_max": 256,
            "version": 1,
        },
        "optics": {"w0_frac": 0.40, "p": 0},
        "channel": {},
    }


def test_five_rep_pack_unpack():
    payload = b"I live in Oregon"
    stream = pack_packet(payload, qec_reps=5)
    recovered, meta = unpack_packet(stream, qec_reps=5)
    assert recovered == payload
    assert meta["crc_ok"]


def test_loopback_qec5():
    result = loopback("I live in Oregon", profile=TEST_PROFILE, cfg=_cfg(5))
    assert result.crc_ok
    assert result.payload == b"I live in Oregon"
