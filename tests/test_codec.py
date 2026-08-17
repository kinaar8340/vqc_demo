from vqc_demo.codec import (
    SYNC_A,
    SYNC_B,
    crc32,
    encode_shard,
    majority_byte,
    pack_packet,
    payload_to_bytes,
    unpack_packet,
    byte_to_bits,
    bits_to_byte,
)


def test_bits_roundtrip():
    for value in range(256):
        assert bits_to_byte(byte_to_bits(value)) == value


def test_majority_byte_corrects_one_flip():
    assert majority_byte([0xA5, 0xA5, 0x00]) == 0xA5
    assert majority_byte([0xFF, 0x00, 0xFF]) == 0xFF


def test_pack_unpack_roundtrip():
    payload = b"I live in Oregon"
    stream = pack_packet(payload, qec_reps=3)
    assert stream[0] == SYNC_A
    assert SYNC_B in stream
    recovered, meta = unpack_packet(stream, qec_reps=3)
    assert recovered == payload
    assert meta["crc_ok"] is True
    assert meta["length"] == len(payload)


def test_qec_survives_single_symbol_corruption():
    payload = b"VQC"
    stream = pack_packet(payload, qec_reps=3)
    # Flip the middle copy of the first payload byte (after 2 sync groups + header).
    # 3+3 sync + 3+3+3 header = 15 symbols before payload.
    stream[16] ^= 0xFF
    recovered, _ = unpack_packet(stream, qec_reps=3)
    assert recovered == payload


def test_crc_detects_damage():
    payload = b"hello"
    stream = pack_packet(payload, qec_reps=3)
    # Corrupt all three copies of the first payload byte so majority cannot save it.
    for i in range(15, 18):
        stream[i] ^= 0x0F
    try:
        unpack_packet(stream, qec_reps=3)
        raised = False
    except ValueError as exc:
        raised = "CRC" in str(exc)
    assert raised


def test_quaternion_unit_norm():
    q = encode_shard(payload_to_bytes("I live in Oregon"))
    assert abs(q.norm() - 1.0) < 1e-9


def test_crc32_stable():
    assert crc32(b"") == 0
    assert crc32(b"123456789") == 0xCBF43926


def test_empty_and_zero_bytes_roundtrip():
    for payload in (b"", b"\x00\x00\x00", b"\x00hello\x00"):
        recovered, _ = unpack_packet(pack_packet(payload, qec_reps=3), qec_reps=3)
        assert recovered == payload
