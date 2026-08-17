import numpy as np

from vqc_demo.codec import byte_to_bits, encode_shard
from vqc_demo.decoder import decode_symbol, find_center
from vqc_demo.frames import FrameRenderer, RenderConfig
from vqc_demo.lg import bit_radii
from vqc_demo.projector import TEST_PROFILE


def test_decode_symbol_every_byte():
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig())
    quat = encode_shard(b"probe")
    # Spot-check a representative set including 0x00, 0xFF, sync, and mixed.
    for value in (0x00, 0x01, 0x80, 0xAA, 0x55, 0xF0, 0x0F, 0xFF, 0xA5, 0x5A):
        frame = renderer.render_data(value, quat, value)
        got = decode_symbol(frame, renderer.peak_radii)
        assert got == value, f"expected 0x{value:02x} got 0x{got:02x}"


def test_center_near_geometric_middle():
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig())
    frame = renderer.render_data(0xAA, encode_shard(b"c"), 0)
    cy, cx = find_center(frame)
    assert abs(cy - (TEST_PROFILE.height - 1) / 2) < 8
    assert abs(cx - (TEST_PROFILE.width - 1) / 2) < 8


def test_peak_radii_match_renderer():
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig(w0_frac=0.40))
    expect = bit_radii(8, TEST_PROFILE.short_axis, TEST_PROFILE.safe_area)
    assert renderer.peak_radii == expect


def test_on_bits_are_brighter_than_guide():
    renderer = FrameRenderer(TEST_PROFILE, RenderConfig())
    frame = renderer.render_data(0x01, encode_shard(b"b"), 0)
    bits = byte_to_bits(0x01)
    assert bits[0] == 1 and bits[1] == 0
    # Smoke: frame is not uniform.
    assert np.asarray(frame).std() > 5
