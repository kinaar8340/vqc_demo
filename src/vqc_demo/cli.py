"""Command-line interface: encode / stitch / decode / loopback / info."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .channel import ChannelModel
from .pipeline import decode_path, encode_to_dir, loopback
from .projector import TEST_PROFILE, load_config, profile_from_config


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vqc-demo",
        description=(
            "VQC intensity-proxy POC: render concentric LG donuts, stitch a "
            "1080p24 MP4 for a Sony VPL-HW20A, and decode a camera capture."
        ),
    )
    p.add_argument("--config", type=Path, default=None, help="YAML config (default: configs/default.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode", help="render PNG sequence (+ MP4) from a payload")
    enc.add_argument("payload", help="UTF-8 text to encode")
    enc.add_argument("-o", "--out", type=Path, default=Path("outputs/tx"))
    enc.add_argument("--no-stitch", action="store_true", help="skip ffmpeg MP4 step")

    st = sub.add_parser("stitch", help="stitch an existing frames/ directory to MP4")
    st.add_argument("frames", type=Path)
    st.add_argument("-o", "--out", type=Path, default=None)

    dec = sub.add_parser("decode", help="decode a captured MP4 or PNG directory")
    dec.add_argument("source", type=Path)
    dec.add_argument("--work-dir", type=Path, default=None)
    dec.add_argument("--expected", default=None, help="known payload for BER logging")

    lp = sub.add_parser("loopback", help="encode→decode in memory (optional capture model)")
    lp.add_argument("payload", nargs="?", default="I live in Oregon")
    lp.add_argument("--channel", action="store_true", help="apply blur/gamma/noise model")
    lp.add_argument(
        "--full",
        action="store_true",
        help="use the 1920×1080 VPL-HW20A profile (default is a fast 320×180 loopback)",
    )

    sub.add_parser("info", help="print projector profile and honesty notes")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cfg = load_config(args.config)
    profile = profile_from_config(cfg)

    if args.cmd == "info":
        print(f"vqc-demo {__version__}")
        print(json.dumps(profile.to_dict(), indent=2))
        print()
        print(
            "This is an intensity RGB-proxy. The VPL-HW20A is a lamp-based SXRD "
            "home-cinema projector: it cannot generate coherent helical phase "
            "fronts exp(iℓφ). Use it to exercise the software decoder and produce "
            "presentation footage. A real OAM link still needs a laser + SLM."
        )
        return 0

    if args.cmd == "encode":
        result = encode_to_dir(
            args.payload,
            args.out,
            profile=profile,
            cfg=cfg,
            stitch=not args.no_stitch,
        )
        print(f"payload  : {result.text!r} ({len(result.payload)} bytes)")
        print(f"symbols  : {result.n_symbols}")
        print(f"frames   : {result.n_frames}  → {result.frames_dir}")
        if result.video_path:
            print(f"video    : {result.video_path}")
        print(f"manifest : {result.manifest_path}")
        print(f"hold     : {profile.hold_frames} frames @ {profile.fps} fps "
              f"({profile.symbol_duration_s*1e3:.0f} ms/symbol)")
        return 0

    if args.cmd == "stitch":
        from .video import stitch_pngs

        dest = args.out or (args.frames.parent / "vqc_poc.mp4")
        path = stitch_pngs(args.frames, dest, profile)
        print(path)
        return 0

    if args.cmd == "decode":
        expected = args.expected.encode("utf-8") if args.expected is not None else None
        result = decode_path(
            args.source,
            profile=profile,
            cfg=cfg,
            work_dir=args.work_dir,
            expected=expected,
        )
        print(result)
        if result.text:
            print(f"text: {result.text}")
        report = result.meta.get("report") or {}
        if report:
            print(json.dumps(report, indent=2))
        return 0 if result.crc_ok else 2

    if args.cmd == "loopback":
        ch = None
        if args.channel:
            ch = ChannelModel(**(cfg.get("channel") or {}))
        result = loopback(
            args.payload,
            profile=profile if args.full else TEST_PROFILE,
            cfg=cfg,
            channel=ch,
            apply_channel=args.channel,
        )
        print(result)
        report = result.meta.get("report") or {}
        if report:
            print(json.dumps(report, indent=2))
        ok = result.crc_ok and result.payload == args.payload.encode("utf-8")
        print("MATCH" if ok else "MISMATCH")
        return 0 if ok else 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
