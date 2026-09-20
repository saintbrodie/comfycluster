from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VideoProbeResult:
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    frame_rate: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container_format: str | None = None
    bit_rate_bps: int | None = None

    def as_metadata_update(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "width": self.width,
                "height": self.height,
                "duration_seconds": self.duration_seconds,
                "frame_count": self.frame_count,
                "frame_rate": self.frame_rate,
                "video_codec": self.video_codec,
                "audio_codec": self.audio_codec,
                "container_format": self.container_format,
                "bit_rate_bps": self.bit_rate_bps,
            }.items()
            if value is not None
        }


def resolve_media_binary(explicit: str | Path | None, default_name: str) -> str | None:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(str(explicit))
        if resolved:
            return resolved
    return shutil.which(default_name)


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _frame_rate(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            parsed = float(numerator) / denominator_value
        except ValueError:
            return None
    else:
        try:
            parsed = float(text)
        except ValueError:
            return None
    return round(parsed, 6) if parsed > 0 else None


def parse_ffprobe_payload(payload: dict[str, Any]) -> VideoProbeResult:
    streams = payload.get("streams") or []
    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        {},
    )
    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        {},
    )
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}

    duration = _positive_float(format_info.get("duration")) or _positive_float(
        video_stream.get("duration")
    )
    bit_rate = _positive_int(format_info.get("bit_rate")) or _positive_int(
        video_stream.get("bit_rate")
    )
    frame_rate = _frame_rate(video_stream.get("avg_frame_rate")) or _frame_rate(
        video_stream.get("r_frame_rate")
    )
    frame_count = _positive_int(video_stream.get("nb_frames"))

    return VideoProbeResult(
        width=_positive_int(video_stream.get("width")),
        height=_positive_int(video_stream.get("height")),
        duration_seconds=duration,
        frame_count=frame_count,
        frame_rate=frame_rate,
        video_codec=str(video_stream.get("codec_name")) if video_stream.get("codec_name") else None,
        audio_codec=str(audio_stream.get("codec_name")) if audio_stream.get("codec_name") else None,
        container_format=str(format_info.get("format_name")) if format_info.get("format_name") else None,
        bit_rate_bps=bit_rate,
    )


def probe_video(
    source: Path,
    *,
    ffprobe_path: str | Path | None = None,
    timeout_seconds: float = 20.0,
) -> VideoProbeResult | None:
    executable = resolve_media_binary(ffprobe_path, "ffprobe")
    if not executable:
        return None
    command = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        payload = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return parse_ffprobe_payload(payload)


def _poster_seek_time(duration_seconds: float | None) -> float:
    if not duration_seconds:
        return 0.5
    return max(0.0, min(duration_seconds * 0.1, 5.0))


def generate_video_poster(
    source: Path,
    destination: Path,
    *,
    size: int,
    duration_seconds: float | None,
    ffmpeg_path: str | Path | None = None,
    timeout_seconds: float = 30.0,
) -> bool:
    executable = resolve_media_binary(ffmpeg_path, "ffmpeg")
    if not executable:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    filter_expr = f"scale={size}:{size}:force_original_aspect_ratio=decrease"
    command = [
        executable,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{_poster_seek_time(duration_seconds):.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        filter_expr,
        "-q:v",
        "3",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout_seconds)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        destination.unlink(missing_ok=True)
        return False
    return destination.is_file() and destination.stat().st_size > 0


def generate_video_preview(
    source: Path,
    destination: Path,
    *,
    duration_seconds: float | None,
    preview_seconds: float = 8.0,
    max_size: int = 720,
    ffmpeg_path: str | Path | None = None,
    timeout_seconds: float = 120.0,
) -> bool:
    executable = resolve_media_binary(ffmpeg_path, "ffmpeg")
    if not executable:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    clip_seconds = max(1.0, min(preview_seconds, 30.0))
    if duration_seconds:
        clip_seconds = min(clip_seconds, duration_seconds)
    scale_expr = (
        f"scale='min({max_size},iw)':'min({max_size},ih)':"
        "force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )
    command = [
        executable,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-t",
        f"{clip_seconds:.3f}",
        "-vf",
        scale_expr,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=timeout_seconds)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        destination.unlink(missing_ok=True)
        return False
    return destination.is_file() and destination.stat().st_size > 0
