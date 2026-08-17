"""Fidelity / error-rate helpers for the intensity-proxy channel."""

from __future__ import annotations

from typing import Any

import numpy as np

from .codec import Quaternion, encode_shard


def hamming_bits(a: bytes, b: bytes) -> tuple[int, int]:
    """Return (bit_errors, bits_compared) after padding the shorter with zeros."""
    n = max(len(a), len(b))
    aa = a.ljust(n, b"\x00")
    bb = b.ljust(n, b"\x00")
    errs = 0
    for x, y in zip(aa, bb):
        errs += (x ^ y).bit_count()
    return errs, n * 8


def qec_disagreement(votes: list[int]) -> float:
    """Fraction of bits in a hold-group that disagree with the majority."""
    if len(votes) < 2:
        return 0.0
    from .codec import majority_byte

    maj = majority_byte(votes)
    bits = 8 * len(votes)
    flips = 0
    for v in votes:
        flips += (v ^ maj).bit_count()
    return flips / bits


def quaternion_error(recovered: Quaternion | None, payload: bytes) -> dict[str, float] | None:
    if recovered is None:
        return None
    expect = encode_shard(payload).unit()
    got = recovered.unit()
    # Chordal / Euclidean error on S^3, plus angular spoke error in the xy plane.
    eucl = float(np.sqrt(sum((a - b) ** 2 for a, b in zip(got.as_tuple(), expect.as_tuple()))))
    ang_e = float(np.arctan2(expect.y, expect.x))
    ang_g = float(np.arctan2(got.y, got.x))
    dphi = abs((ang_g - ang_e + np.pi) % (2 * np.pi) - np.pi)
    return {
        "euclidean": eucl,
        "spoke_abs_rad": dphi,
        "spoke_abs_deg": float(np.degrees(dphi)),
    }


def build_report(
    *,
    payload: bytes,
    text: str,
    crc_ok: bool,
    expected: bytes | None,
    qec_disagree_mean: float,
    ring_snr_db: float | None,
    quat: Quaternion | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "crc_ok": crc_ok,
        "payload_len": len(payload),
        "payload_text": text,
        "qec_disagreement": qec_disagree_mean,
        "ring_snr_db": ring_snr_db,
        "disclaimer": (
            "Intensity RGB-proxy metrics only. Not a coherent-OAM BER, "
            "and not a physical BMGL / turbulence measurement."
        ),
    }
    if expected is not None:
        bit_err, nbits = hamming_bits(payload, expected)
        report["expected_len"] = len(expected)
        report["bit_errors"] = bit_err
        report["bits_compared"] = nbits
        report["ber"] = (bit_err / nbits) if nbits else 0.0
        report["exact_match"] = payload == expected
    qerr = quaternion_error(quat, payload)
    if qerr is not None:
        report["quaternion"] = qerr
    if extra:
        report.update(extra)
    return report
