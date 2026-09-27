import logging
import math
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.core.paths import find_binary, get_cache_dir
from src.media.probe import probe_video

logger = logging.getLogger(__name__)

def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    secs = int(round(seconds))
    hrs = secs // 3600
    mins = (secs % 3600) // 60
    rem_secs = secs % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{rem_secs:02d}"
    return f"{mins:02d}:{rem_secs:02d}"

def extract_frames(
    video_path: Path,
    interval_seconds: int = 60,
    max_frames: int = 30,
    max_dimension: int = 768,
    strategy: str = "interval",
    key_moments_count: int = 20,
    custom_ffmpeg: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Extract frames at regular intervals or key moments with associated timestamps.
    Engineered for rock-solid stability on long videos up to multiple hours.
    Returns list of dicts: {'path': Path, 'timestamp_seconds': float, 'timecode': str}
    """
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found. Please install ffmpeg or configure its path.")

    # Probe duration
    info = probe_video(video_path, custom_ffprobe=None)
    duration = float(info.get("duration", 0.0))

    # Determine frame timestamps
    timestamps: List[float] = []
    if duration <= 0:
        timestamps = [0.0]
    elif strategy in ("key_moments", "scene_change"):
        # Milestone key moments distributed across the video narrative
        target_count = max(2, min(key_moments_count, max_frames))
        if target_count == 2:
            timestamps = [0.0, max(0.0, duration - 1.0)]
        else:
            step = duration / (target_count - 1)
            raw_ts = [i * step for i in range(target_count)]
            raw_ts[-1] = max(0.0, min(duration - 0.5, raw_ts[-1]))
            timestamps = sorted(list(set([round(t, 2) for t in raw_ts])))
    else:
        # Interval-based sampling: candidate timestamps at interval_seconds
        step_sec = max(1.0, float(interval_seconds))
        cand: List[float] = []
        curr = 0.0
        while curr < duration:
            cand.append(round(curr, 2))
            curr += step_sec

        if not cand:
            cand = [0.0]

        # If candidates exceed max_frames, uniformly decimate to span full video safely
        if len(cand) > max_frames:
            if max_frames <= 1:
                timestamps = [cand[0]]
            else:
                indices = [int(round(i * (len(cand) - 1) / (max_frames - 1))) for i in range(max_frames)]
                timestamps = sorted(list(set([cand[idx] for idx in indices])))
        else:
            timestamps = cand

    # Output directory in cache
    video_hash = f"{video_path.stem}_{int(video_path.stat().st_mtime)}"
    frame_dir = get_cache_dir() / "frames" / video_hash
    frame_dir.mkdir(parents=True, exist_ok=True)

    extracted: List[Dict[str, Any]] = []

    scale_filter = f"scale='min({max_dimension},iw)':-1:flags=lanczos"

    for idx, ts in enumerate(timestamps):
        frame_name = f"frame_{idx:04d}_{int(ts)}s.jpg"
        out_frame = frame_dir / frame_name

        # If already cached, reuse
        if not out_frame.exists() or out_frame.stat().st_size == 0:
            cmd = [
                ffmpeg_bin,
                "-y",
                "-ss", str(ts),
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", scale_filter,
                "-q:v", "3",
                str(out_frame)
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception as e:
                logger.warning(f"Failed to extract frame at {ts}s for {video_path.name}: {e}")
                continue

        if out_frame.exists() and out_frame.stat().st_size > 0:
            extracted.append({
                "path": str(out_frame),
                "timestamp_seconds": ts,
                "timecode": format_timestamp(ts)
            })

    return extracted

def extract_audio(
    video_path: Path,
    custom_ffmpeg: Optional[str] = None
) -> Optional[Path]:
    """
    Extract audio track to 16kHz mono WAV suitable for Whisper models.
    Returns path to WAV or None if video has no audio.
    """
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found.")

    video_hash = f"{video_path.stem}_{int(video_path.stat().st_mtime)}"
    audio_dir = get_cache_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_audio = audio_dir / f"{video_hash}.wav"

    if out_audio.exists() and out_audio.stat().st_size > 0:
        return out_audio

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(out_audio)
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            # Check if reason was missing audio stream
            if "does not contain any stream" in res.stderr or "Output file #0 does not contain any stream" in res.stderr:
                logger.info(f"Video {video_path.name} has no audio stream.")
                return None
            logger.warning(f"Audio extraction warning for {video_path.name}: {res.stderr}")
            return None
    except Exception as e:
        logger.error(f"Audio extraction failed for {video_path}: {e}")
        return None

    if out_audio.exists() and out_audio.stat().st_size > 0:
        return out_audio
    return None
