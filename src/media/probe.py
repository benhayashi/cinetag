import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from src.core.paths import find_binary

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".wmv", ".flv", ".mts", ".m2ts"
}

def is_video_file(path: Path) -> bool:
    """Check if file has a supported video extension."""
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS

def probe_video(video_path: Path, custom_ffprobe: Optional[str] = None) -> Dict[str, Any]:
    """Extract metadata from video using ffprobe."""
    ffprobe_bin = find_binary("ffprobe", custom_ffprobe)
    
    stat = video_path.stat()
    fallback_meta = {
        "path": str(video_path),
        "filename": video_path.name,
        "extension": video_path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "creation_time": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "video_codec": "unknown",
        "audio_codec": None,
        "has_audio": False,
        "ffprobe_available": False,
        "tags": {}
    }

    if not ffprobe_bin:
        logger.warning(f"ffprobe binary not found. Returning basic file stats for {video_path.name}")
        return fallback_meta

    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path)
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
    except Exception as e:
        logger.error(f"ffprobe failed for {video_path}: {e}")
        return fallback_meta

    streams = data.get("streams", [])
    format_info = data.get("format", {})
    tags = format_info.get("tags", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    # Accompanying .srt check
    from src.media.subtitles import find_accompanying_srt
    acc_srt = find_accompanying_srt(video_path)

    duration = float(format_info.get("duration", 0.0))
    if duration == 0.0 and video_stream and "duration" in video_stream:
        try:
            duration = float(video_stream["duration"])
        except (ValueError, TypeError):
            pass

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    vcodec = video_stream.get("codec_name", "unknown") if video_stream else "none"
    acodec = audio_stream.get("codec_name") if audio_stream else None

    # Determine best date
    creation_str = tags.get("creation_time") or tags.get("date")
    if creation_str:
        # Standardize ISO or similar
        date_val = creation_str
    else:
        date_val = datetime.fromtimestamp(stat.st_mtime).isoformat()

    return {
        "path": str(video_path),
        "filename": video_path.name,
        "extension": video_path.suffix.lower(),
        "size_bytes": stat.st_size,
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": vcodec,
        "audio_codec": acodec,
        "has_audio": audio_stream is not None,
        "has_subtitles": bool(acc_srt or subtitle_streams),
        "has_external_srt": acc_srt is not None,
        "external_srt_path": str(acc_srt.resolve()) if acc_srt else None,
        "embedded_subtitles_count": len(subtitle_streams),
        "creation_time": date_val,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "ffprobe_available": True,
        "tags": tags
    }
