"""Published software-fidelity sweeps. Not a free-space OAM BER."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .channel import PRESETS, ChannelModel
from .pipeline import loopback
from .projector import TEST_PROFILE


def run_case(
    payload: str,
    channel: ChannelModel,
    *,
    qec_reps: int = 3,
    apply_channel: bool = True,
) -> dict[str, Any]:
    cfg = {
        "encode": {
            "qec_reps": qec_reps,
            "n_rings": 8,
            "guide_level": 0.08,
            "on_level": 1.0,
            "payload_max": 256,
            "version": 1,
        },
        "optics": {"w0_frac": 0.40, "p": 0},
        "channel": {},
    }
    try:
        result = loopback(
            payload,
            profile=TEST_PROFILE,
            cfg=cfg,
            channel=channel,
            apply_channel=apply_channel,
        )
        report = result.meta.get("report") or {}
        return {
            "ok": bool(result.crc_ok and result.payload == payload.encode("utf-8")),
            "crc_ok": result.crc_ok,
            "exact_match": result.payload == payload.encode("utf-8"),
            "ber": report.get("ber"),
            "qec_disagreement": report.get("qec_disagreement"),
            "ring_snr_db": report.get("ring_snr_db"),
            "spoke_abs_deg": (report.get("quaternion") or {}).get("spoke_abs_deg"),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — stress must not abort the sweep
        return {
            "ok": False,
            "crc_ok": False,
            "exact_match": False,
            "ber": None,
            "qec_disagreement": None,
            "ring_snr_db": None,
            "spoke_abs_deg": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_sweep(
    payload: str = "I live in Oregon",
    *,
    qec_reps: tuple[int, ...] = (3, 5),
    presets: tuple[str, ...] = ("clean", "projector", "kolmogorov", "bmgl"),
    seeds: tuple[int, ...] = (0, 1, 2),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for reps in qec_reps:
        for name in presets:
            ch0 = PRESETS[name]
            apply = name != "clean"
            seed_list = (0,) if not apply else seeds
            for seed in seed_list:
                ch = ch0.with_seed(seed)
                case = run_case(payload, ch, qec_reps=reps, apply_channel=apply)
                case.update(
                    {
                        "preset": name,
                        "qec_reps": reps,
                        "seed": seed,
                        "payload": payload,
                    }
                )
                rows.append(case)

    n_ok = sum(1 for r in rows if r["ok"])
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "vqc_demo_version": __version__,
        "payload": payload,
        "profile": "TEST_PROFILE 320x180",
        "n_cases": len(rows),
        "n_ok": n_ok,
        "pass_rate": n_ok / len(rows) if rows else 0.0,
        "disclaimer": (
            "Software intensity-proxy metrics on a 320×180 loopback. "
            "Not a coherent-OAM link BER and not a physical BMGL measurement."
        ),
        "cases": rows,
    }
    return summary


def write_metrics(path: str | Path, summary: dict[str, Any] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = summary or run_sweep()
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path
