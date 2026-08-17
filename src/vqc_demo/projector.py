"""Sony VPL-HW20A (and generic) projector profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ProjectorProfile:
    """Display / encode target for the intensity-proxy channel."""

    name: str = "Sony VPL-HW20A"
    width: int = 1920
    height: int = 1080
    fps: float = 24.0
    hold_frames: int = 8
    pix_fmt: str = "yuv420p"
    crf: int = 18
    safe_area: float = 0.88
    codec: str = "libx264"

    @property
    def short_axis(self) -> int:
        return min(self.width, self.height)

    @property
    def symbol_duration_s(self) -> float:
        return self.hold_frames / self.fps

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VPL_HW20A = ProjectorProfile()

# Fast CI / unit-test geometry. Rings still fit; decode math is identical.
TEST_PROFILE = ProjectorProfile(
    name="test-320x180",
    width=320,
    height=180,
    fps=24.0,
    hold_frames=2,
    safe_area=0.86,
    crf=23,
)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config; missing file falls back to built-in defaults."""
    if path is None:
        here = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"
        path = here if here.is_file() else None
    if path is None:
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def profile_from_config(cfg: dict[str, Any] | None = None) -> ProjectorProfile:
    block = (cfg or {}).get("projector") or {}
    base = asdict(VPL_HW20A)
    base.update({k: block[k] for k in base if k in block})
    return ProjectorProfile(**base)
