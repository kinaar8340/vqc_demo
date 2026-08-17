"""ffmpeg stitch / extract helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .projector import ProjectorProfile, VPL_HW20A


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FFmpegError("ffmpeg not found on PATH")
    return path


def stitch_pngs(
    frames_dir: Path,
    dest: Path,
    profile: ProjectorProfile | None = None,
    stem: str = "frame",
) -> Path:
    """Turn frame_00000.png … into a 1080p24 H.264 MP4."""
    profile = profile or VPL_HW20A
    dest.parent.mkdir(parents=True, exist_ok=True)
    pattern = str(frames_dir / f"{stem}_%05d.png")
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-framerate",
        str(profile.fps),
        "-i",
        pattern,
        "-c:v",
        profile.codec,
        "-pix_fmt",
        profile.pix_fmt,
        "-s",
        f"{profile.width}x{profile.height}",
        "-crf",
        str(profile.crf),
        "-tune",
        "stillimage",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    _run(cmd)
    return dest


def extract_pngs(
    video: Path,
    dest_dir: Path,
    stem: str = "cap",
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(dest_dir / f"{stem}_%05d.png")
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        str(video),
        "-vsync",
        "0",
        pattern,
    ]
    _run(cmd)
    return sorted(dest_dir.glob(f"{stem}_*.png"))


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
