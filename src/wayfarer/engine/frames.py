"""Turn a Beli scroll screen-recording into a small set of frames to read.

Uses ffmpeg's mpdecimate filter to drop near-duplicate frames (a slow scroll
with brief pauses yields roughly one frame per screen), so we don't need any
Python image libraries. Residual overlap is handled downstream by
engine.taste.dedup_entries.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_cmd(video: str, out_pattern: str, fps: int = 2) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", video,
        "-vf", f"fps={fps},mpdecimate",
        "-vsync", "vfr",
        out_pattern,
    ]


def extract_frames(video: str | Path, out_dir: str | Path, fps: int = 2) -> list[Path]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH. Install it (`brew install ffmpeg`).")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Remove stale frames so a shorter re-recording doesn't leave extra frames.
    for stale in out.glob("frame_*.png"):
        stale.unlink()
    pattern = str(out / "frame_%04d.png")
    proc = subprocess.run(
        ffmpeg_cmd(str(video), pattern, fps=fps),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
    return sorted(out.glob("frame_*.png"))
