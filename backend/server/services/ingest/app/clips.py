"""Сборка MP4 (H.264, играет в <video>) из JPEG-кадров кольцевого буфера через ffmpeg."""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import UTC, datetime


def clip_key(event_id: str, ts: float) -> str:
    return f"clips/{datetime.fromtimestamp(ts, UTC):%Y/%m/%d}/{event_id}.mp4"


def encode_mp4(frames: list[tuple[float, bytes]]) -> bytes:
    dur = frames[-1][0] - frames[0][0]
    fps = max(1, round((len(frames) - 1) / dur)) if dur > 0 else 5
    fd, out = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart", out]
        proc = subprocess.run(cmd, input=b"".join(f[1] for f in frames), capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-500:])
        with open(out, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
