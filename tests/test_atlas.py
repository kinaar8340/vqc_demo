from vqc_demo.codec import (
    ATLAS_24,
    encode_shard,
    encode_shard_atlas,
    snap_to_atlas,
)


def test_atlas_has_24_unit_points():
    assert len(ATLAS_24) == 24
    for q in ATLAS_24:
        assert abs(q.norm() - 1.0) < 1e-9


def test_snap_is_idempotent():
    for q in ATLAS_24:
        snapped, idx = snap_to_atlas(q)
        again, idx2 = snap_to_atlas(snapped)
        assert idx == idx2
        assert snapped.as_tuple() == again.as_tuple()


def test_payload_maps_into_atlas():
    q, idx = encode_shard_atlas(b"I live in Oregon")
    assert 0 <= idx < 24
    assert abs(q.norm() - 1.0) < 1e-9
    # Snapping the raw shard lands on the same vertex.
    raw = encode_shard(b"I live in Oregon")
    snapped, j = snap_to_atlas(raw)
    assert j == idx
    assert snapped.as_tuple() == q.as_tuple()
