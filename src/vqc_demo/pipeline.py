"""Encode payload → PNG sequence → MP4, and the reverse decode path."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .channel import ChannelModel
from .codec import encode_shard, pack_packet, payload_to_bytes
from .decoder import DecodeResult, decode_frames, decode_png_dir, load_frames
from .frames import FrameRenderer, RenderConfig, contact_sheet, save_png, write_sequence
from .projector import ProjectorProfile, VPL_HW20A, load_config, profile_from_config
from .video import extract_pngs, stitch_pngs


@dataclass
class EncodeResult:
    out_dir: Path
    frames_dir: Path
    video_path: Path | None
    manifest_path: Path
    n_frames: int
    n_symbols: int
    payload: bytes
    text: str


def _render_cfg(cfg: dict[str, Any]) -> RenderConfig:
    enc = cfg.get("encode") or {}
    opt = cfg.get("optics") or {}
    return RenderConfig(
        n_rings=int(enc.get("n_rings", 8)),
        guide_level=float(enc.get("guide_level", 0.08)),
        on_level=float(enc.get("on_level", 1.0)),
        w0_frac=float(opt.get("w0_frac", 0.40)),
        p=int(opt.get("p", 0)),
    )


def build_frames(
    payload: str | bytes,
    *,
    profile: ProjectorProfile | None = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[list, dict[str, Any]]:
    cfg = cfg if cfg is not None else load_config()
    profile = profile or profile_from_config(cfg)
    enc = cfg.get("encode") or {}
    qec_reps = int(enc.get("qec_reps", 3))
    data = payload_to_bytes(payload)
    max_n = int(enc.get("payload_max", 256))
    if len(data) > max_n:
        raise ValueError(f"payload {len(data)} bytes exceeds payload_max={max_n}")

    symbols = pack_packet(data, qec_reps=qec_reps, version=int(enc.get("version", 1)))
    quat = encode_shard(data)
    renderer = FrameRenderer(profile, _render_cfg(cfg))

    frames = []
    # Lead-in / tail must be multiples of hold_frames so symbol grouping stays aligned.
    def _hold_aligned(seconds: float) -> int:
        raw = max(profile.hold_frames, int(round(profile.fps * seconds)))
        return ((raw + profile.hold_frames - 1) // profile.hold_frames) * profile.hold_frames

    n_calib = _hold_aligned(1.0)
    n_black = _hold_aligned(0.5)
    calib = renderer.render_calib()
    black = renderer.render_black()
    frames.extend([calib] * n_calib)
    frames.extend([black] * n_black)
    n_sym = max(1, len(symbols))
    for i, sym in enumerate(symbols):
        # Triangle envelope 0→1→0 across the packet (pyramidal-FM visual proxy).
        t = i / (n_sym - 1) if n_sym > 1 else 0.5
        pulse = 1.0 - abs(2.0 * t - 1.0)
        frame = renderer.render_data(sym, quat, i, pulse=pulse)
        frames.extend([frame] * profile.hold_frames)
    frames.extend([black] * n_black)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "payload_text": data.decode("utf-8", errors="replace"),
        "payload_hex": data.hex(),
        "payload_len": len(data),
        "qec_reps": qec_reps,
        "n_symbols": len(symbols),
        "n_frames": len(frames),
        "hold_frames": profile.hold_frames,
        "quaternion": list(quat.as_tuple()),
        "projector": profile.to_dict(),
        "peak_radii_px": renderer.peak_radii,
        "w0_px": renderer.w0,
        "disclaimer": (
            "Intensity RGB-proxy only. The VPL-HW20A cannot emit coherent "
            "Laguerre-Gaussian OAM modes; this POC exercises the software decoder."
        ),
    }
    return frames, manifest


def encode_to_dir(
    payload: str | bytes,
    out_dir: str | Path,
    *,
    profile: ProjectorProfile | None = None,
    cfg: dict[str, Any] | None = None,
    stitch: bool = True,
) -> EncodeResult:
    cfg = cfg if cfg is not None else load_config()
    profile = profile or profile_from_config(cfg)
    out_dir = Path(out_dir)
    frames_dir = out_dir / ((cfg.get("paths") or {}).get("frames_subdir") or "frames")
    video_name = (cfg.get("paths") or {}).get("video_name") or "vqc_poc.mp4"
    man_name = (cfg.get("paths") or {}).get("manifest_name") or "manifest.json"

    frames, manifest = build_frames(payload, profile=profile, cfg=cfg)
    write_sequence(frames_dir, frames)
    sheet = contact_sheet(frames[:: max(1, profile.hold_frames)])
    save_png(out_dir / "contact_sheet.png", sheet)

    man_path = out_dir / man_name
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out_dir / "ffmpeg.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'ffmpeg -y -framerate {profile.fps} -i "{frames_dir}/frame_%05d.png" '
        f"-c:v {profile.codec} -pix_fmt {profile.pix_fmt} "
        f"-s {profile.width}x{profile.height} -crf {profile.crf} "
        f"-tune stillimage -movflags +faststart "
        f'"{out_dir / video_name}"\n',
        encoding="utf-8",
    )

    video_path = None
    if stitch:
        video_path = stitch_pngs(frames_dir, out_dir / video_name, profile)

    data = payload_to_bytes(payload)
    return EncodeResult(
        out_dir=out_dir,
        frames_dir=frames_dir,
        video_path=video_path,
        manifest_path=man_path,
        n_frames=len(frames),
        n_symbols=int(manifest["n_symbols"]),
        payload=data,
        text=data.decode("utf-8", errors="replace"),
    )


def decode_path(
    source: str | Path,
    *,
    profile: ProjectorProfile | None = None,
    cfg: dict[str, Any] | None = None,
    work_dir: str | Path | None = None,
    expected: bytes | None = None,
) -> DecodeResult:
    cfg = cfg if cfg is not None else load_config()
    profile = profile or profile_from_config(cfg)
    enc = cfg.get("encode") or {}
    opt = cfg.get("optics") or {}
    source = Path(source)
    kwargs = dict(
        profile=profile,
        hold_frames=profile.hold_frames,
        n_rings=int(enc.get("n_rings", 8)),
        w0_frac=float(opt.get("w0_frac", 0.40)),
        qec_reps=int(enc.get("qec_reps", 3)),
        expected=expected,
    )
    if source.is_dir():
        result = decode_png_dir(source, **kwargs)
    elif source.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        raise ValueError("pass a directory of frames or an .mp4, not a single image")
    else:
        dest = Path(work_dir) if work_dir else source.parent / (source.stem + "_frames")
        paths = extract_pngs(source, dest)
        result = decode_frames(load_frames(paths), **kwargs)
    report_dir = source if source.is_dir() else source.parent
    (report_dir / "fidelity.json").write_text(
        json.dumps(result.meta.get("report", {}), indent=2),
        encoding="utf-8",
    )
    return result


def loopback(
    payload: str | bytes,
    *,
    profile: ProjectorProfile | None = None,
    cfg: dict[str, Any] | None = None,
    channel: ChannelModel | None = None,
    apply_channel: bool = False,
) -> DecodeResult:
    """Encode in memory and decode immediately (optional capture model)."""
    cfg = cfg if cfg is not None else load_config()
    profile = profile or profile_from_config(cfg)
    frames, _ = build_frames(payload, profile=profile, cfg=cfg)
    if apply_channel:
        model = channel or ChannelModel(**((cfg.get("channel") or {})))
        frames = [model.apply(f) for f in frames]
    enc = cfg.get("encode") or {}
    opt = cfg.get("optics") or {}
    return decode_frames(
        frames,
        profile=profile,
        hold_frames=profile.hold_frames,
        n_rings=int(enc.get("n_rings", 8)),
        w0_frac=float(opt.get("w0_frac", 0.40)),
        qec_reps=int(enc.get("qec_reps", 3)),
        expected=payload_to_bytes(payload),
    )
