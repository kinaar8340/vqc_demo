"""Packet codec: payload → framed bytes with CRC32 and [[3,1,3]] QEC."""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

import numpy as np

# Distinctive ring patterns (alternating / inverse / nibble block).
SYNC_A = 0xAA
SYNC_B = 0x55
SYNC_END = 0xF0
VERSION = 1
# XOR body bytes so 0x00 length/payload never looks like a black frame.
WHITEN = 0xA5


@dataclass(frozen=True)
class Quaternion:
    w: float
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def norm(self) -> float:
        return float(np.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2))

    def unit(self) -> Quaternion:
        n = self.norm()
        if n == 0:
            return Quaternion(1.0, 0.0, 0.0, 0.0)
        return Quaternion(self.w / n, self.x / n, self.y / n, self.z / n)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.w, self.x, self.y, self.z)


def payload_to_bytes(payload: str | bytes) -> bytes:
    if isinstance(payload, bytes):
        return payload
    return payload.encode("utf-8")


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def encode_shard(data: bytes) -> Quaternion:
    """Map payload bytes onto a unit quaternion (visual spoke only)."""
    digest = hashlib.sha256(data).digest()
    raw = np.frombuffer(digest[:16], dtype=np.int32).astype(np.float64)
    raw = raw - raw.mean()
    n = np.linalg.norm(raw)
    if n == 0:
        return Quaternion(1.0, 0.0, 0.0, 0.0)
    raw = raw / n
    return Quaternion(*raw)


def repetition_encode_byte(value: int, reps: int = 3) -> list[int]:
    return [int(value) & 0xFF] * reps


def majority_byte(samples: list[int]) -> int:
    if not samples:
        raise ValueError("majority_byte on empty sample list")
    # Bitwise majority across the sample set.
    acc = 0
    n = len(samples)
    for bit in range(8):
        ones = sum((s >> bit) & 1 for s in samples)
        if ones * 2 >= n:
            acc |= 1 << bit
    return acc


def pack_packet(payload: bytes, *, qec_reps: int = 3, version: int = VERSION) -> list[int]:
    """
    Logical byte stream (each entry later becomes one ring-symbol):

        SYNC_A × reps, SYNC_B × reps,
        len_hi, len_lo, version,   # each × reps
        payload..., crc32 (4 bytes)
        SYNC_END × reps
    """
    if len(payload) > 0xFFFF:
        raise ValueError("payload exceeds 65535 bytes")
    csum = crc32(payload)
    header = struct.pack(">H B", len(payload), version & 0xFF)
    body = header + payload + struct.pack(">I", csum)
    body = bytes(b ^ WHITEN for b in body)

    stream: list[int] = []
    stream.extend(repetition_encode_byte(SYNC_A, qec_reps))
    stream.extend(repetition_encode_byte(SYNC_B, qec_reps))
    for b in body:
        stream.extend(repetition_encode_byte(b, qec_reps))
    stream.extend(repetition_encode_byte(SYNC_END, qec_reps))
    return stream


def unpack_packet(symbols: list[int], *, qec_reps: int = 3) -> tuple[bytes, dict]:
    """Recover payload from a decoded symbol stream. Raises ValueError on framing/CRC fail."""
    if qec_reps < 1:
        raise ValueError("qec_reps must be >= 1")

    # Collapse QEC groups, allowing a sliding start so a clipped preamble still works.
    logical = _collapse_qec(symbols, qec_reps)
    meta: dict = {"logical": logical, "qec_reps": qec_reps}

    idx = _find_sync(logical)
    if idx is None:
        raise ValueError("sync markers 0xAA 0x55 not found")
    meta["sync_index"] = idx
    cursor = idx + 2

    if cursor + 3 > len(logical):
        raise ValueError("truncated header after sync")
    hdr = [b ^ WHITEN for b in logical[cursor : cursor + 3]]
    length = (hdr[0] << 8) | hdr[1]
    version = hdr[2]
    cursor += 3
    meta["length"] = length
    meta["version"] = version

    need = length + 4
    if cursor + need > len(logical):
        raise ValueError(f"truncated payload (need {need} bytes, have {len(logical) - cursor})")
    payload = bytes(b ^ WHITEN for b in logical[cursor : cursor + length])
    crc_bytes = [b ^ WHITEN for b in logical[cursor + length : cursor + length + 4]]
    got_crc = (
        (crc_bytes[0] << 24) | (crc_bytes[1] << 16) | (crc_bytes[2] << 8) | crc_bytes[3]
    )
    expect = crc32(payload)
    meta["crc_ok"] = got_crc == expect
    meta["crc"] = got_crc
    if got_crc != expect:
        raise ValueError(f"CRC mismatch: got 0x{got_crc:08x} expected 0x{expect:08x}")
    return payload, meta


def _collapse_qec(symbols: list[int], reps: int) -> list[int]:
    if reps == 1:
        return [s & 0xFF for s in symbols]
    best: list[int] | None = None
    for offset in range(reps):
        grouped: list[int] = []
        i = offset
        while i + reps <= len(symbols):
            grouped.append(majority_byte(symbols[i : i + reps]))
            i += reps
        if best is None or _sync_score(grouped) > _sync_score(best):
            best = grouped
    return best or []


def _sync_score(logical: list[int]) -> int:
    score = 0
    for i in range(len(logical) - 1):
        if logical[i] == SYNC_A and logical[i + 1] == SYNC_B:
            score += 10
        if logical[i] == SYNC_END:
            score += 1
    return score


def _find_sync(logical: list[int]) -> int | None:
    for i in range(len(logical) - 1):
        if logical[i] == SYNC_A and logical[i + 1] == SYNC_B:
            return i
    return None


def byte_to_bits(value: int, n_bits: int = 8) -> np.ndarray:
    """LSB of ``value`` is ring 0 (|ℓ|=1)."""
    bits = np.zeros(n_bits, dtype=np.uint8)
    for i in range(n_bits):
        bits[i] = (value >> i) & 1
    return bits


def bits_to_byte(bits: np.ndarray) -> int:
    value = 0
    for i, b in enumerate(bits.astype(int).ravel()[:8]):
        if b:
            value |= 1 << i
    return value
