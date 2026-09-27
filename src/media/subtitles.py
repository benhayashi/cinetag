import logging
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.core.paths import find_binary

logger = logging.getLogger(__name__)

def parse_srt_file(srt_path: Path) -> str:
    """
    Parse an SRT subtitle file into clean dialogue text with time markers.
    Strips subtitle index numbers and formatting tags (e.g. <i>, <b>, <font>).
    """
    if not srt_path.exists() or srt_path.stat().st_size == 0:
        return ""

    try:
        content = srt_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Error reading SRT file at {srt_path}: {e}")
        return ""

    return clean_srt_content(content)

def clean_srt_content(srt_text: str) -> str:
    """Clean raw SRT text into sequential dialogue lines."""
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    dialogue_lines: List[str] = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        # Look for timestamp line (e.g. 00:01:20,000 --> 00:01:23,000)
        ts_index = -1
        timecode = ""
        for i, l in enumerate(lines):
            match = re.search(r'(\d{2}:\d{2}:\d{2})[,.]\d{3}\s*-->\s*(\d{2}:\d{2}:\d{2})', l)
            if match:
                ts_index = i
                start_full = match.group(1)
                # Shorten HH:MM:SS to MM:SS if hours are 00
                if start_full.startswith("00:"):
                    timecode = start_full[3:]
                else:
                    timecode = start_full
                break

        # Dialogue text lines are those following the timestamp
        if ts_index != -1 and ts_index + 1 < len(lines):
            raw_dialogue = " ".join(lines[ts_index + 1:])
            # Strip HTML tags like <i>, </b>, <font color="...">
            clean_line = re.sub(r'<[^>]+>', '', raw_dialogue).strip()
            # Clean bracketed notes like [Applause] or (Music)
            clean_line = re.sub(r'\[.*?\]|\(.*?\)', '', clean_line).strip()
            if clean_line:
                if timecode:
                    dialogue_lines.append(f"[{timecode}] {clean_line}")
                else:
                    dialogue_lines.append(clean_line)

    return "\n".join(dialogue_lines)

def find_accompanying_srt(video_path: Path) -> Optional[Path]:
    """
    Search for an accompanying .srt file in the same directory as the video.
    Checks:
      1. video_stem.srt (e.g., vacation.srt)
      2. video_name.srt (e.g., vacation.mp4.srt)
      3. video_stem.en.srt, video_stem.eng.srt, video_stem.default.srt
    """
    parent = video_path.parent
    if not parent.exists():
        return None

    stem = video_path.stem
    candidates = [
        parent / f"{stem}.srt",
        parent / f"{video_path.name}.srt",
        parent / f"{stem}.en.srt",
        parent / f"{stem}.eng.srt",
        parent / f"{stem}.default.srt",
    ]

    for cand in candidates:
        if cand.exists() and cand.is_file() and cand.stat().st_size > 0:
            return cand

    # Case-insensitive search in directory for matching stem
    try:
        lower_stem = stem.lower()
        for f in parent.iterdir():
            if f.is_file() and f.suffix.lower() == ".srt":
                f_stem_lower = f.stem.lower()
                if f_stem_lower == lower_stem or f_stem_lower.startswith(f"{lower_stem}."):
                    return f
    except Exception:
        pass

    return None

def extract_embedded_subtitles(video_path: Path, custom_ffmpeg: Optional[str] = None) -> Optional[str]:
    """
    Extract first subtitle stream embedded in video container to text using ffmpeg.
    Returns parsed dialogue string or None if no subtitle streams found.
    """
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    if not ffmpeg_bin:
        return None

    cmd = [
        ffmpeg_bin,
        "-y",
        "-v", "quiet",
        "-i", str(video_path),
        "-map", "0:s:0",
        "-f", "srt",
        "pipe:1"
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if res.returncode == 0 and res.stdout.strip():
            return clean_srt_content(res.stdout)
    except Exception as e:
        logger.debug(f"Failed to extract embedded subtitles from {video_path.name}: {e}")

    return None

def get_video_subtitles(
    video_path: Path,
    custom_ffmpeg: Optional[str] = None
) -> Dict[str, Any]:
    """
    Locate subtitles for a video by checking:
    1. Accompanying .srt file in the same directory.
    2. Embedded subtitle tracks inside the video container.
    Returns:
      {
        "has_subtitles": bool,
        "source": "external_srt" | "embedded" | "none",
        "srt_path": Optional[str],
        "dialogue_text": Optional[str]
      }
    """
    # 1. Check external .srt
    ext_srt = find_accompanying_srt(video_path)
    if ext_srt:
        text = parse_srt_file(ext_srt)
        if text.strip():
            return {
                "has_subtitles": True,
                "source": "external_srt",
                "srt_path": str(ext_srt.resolve()),
                "dialogue_text": text
            }

    # 2. Check embedded subtitles
    emb_text = extract_embedded_subtitles(video_path, custom_ffmpeg=custom_ffmpeg)
    if emb_text and emb_text.strip():
        return {
            "has_subtitles": True,
            "source": "embedded",
            "srt_path": None,
            "dialogue_text": emb_text
        }

    return {
        "has_subtitles": False,
        "source": "none",
        "srt_path": None,
        "dialogue_text": None
    }

def format_timestamp_srt(seconds: float) -> str:
    """Format seconds (e.g. 75.25) into standard SRT timestamp HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    total_secs = int(seconds)
    secs = total_secs % 60
    mins = (total_secs // 60) % 60
    hours = total_secs // 3600
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def generate_srt_from_text(
    text: str,
    total_duration: Optional[float] = None,
    segments: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Generate valid .srt formatted subtitle text from timestamped segments or raw transcript.
    """
    if segments:
        blocks = []
        idx = 1
        for seg in segments:
            seg_text = seg.get("text", "").strip()
            if not seg_text:
                continue
            start_s = float(seg.get("start", 0.0))
            end_s = float(seg.get("end", start_s + 3.0))
            if end_s <= start_s:
                end_s = start_s + 1.0
            start_str = format_timestamp_srt(start_s)
            end_str = format_timestamp_srt(end_s)
            blocks.append(f"{idx}\n{start_str} --> {end_str}\n{seg_text}")
            idx += 1
        if blocks:
            return "\n\n".join(blocks) + "\n"

    # Fallback: chunk plain text into natural phrases (approx 6-10 words per 3-4s cue)
    words = text.strip().split()
    if not words:
        return ""

    blocks = []
    chunk_size = 8
    duration = total_duration or max(10.0, len(words) * 0.45)
    time_per_word = duration / max(1, len(words))

    idx = 1
    current_pos = 0.0
    for i in range(0, len(words), chunk_size):
        chunk_words = words[i:i + chunk_size]
        start_s = current_pos
        end_s = current_pos + len(chunk_words) * time_per_word
        start_str = format_timestamp_srt(start_s)
        end_str = format_timestamp_srt(end_s)
        blocks.append(f"{idx}\n{start_str} --> {end_str}\n{' '.join(chunk_words)}")
        idx += 1
        current_pos = end_s

    return "\n\n".join(blocks) + "\n"

def write_srt_sidecar(
    video_path: Path,
    srt_content: str,
    conflict_mode: str = "overwrite"
) -> Path:
    """
    Write .srt subtitle file next to video. Respects conflict mode (overwrite vs enumerate).
    """
    base_path = video_path.parent / f"{video_path.stem}.srt"
    from src.exporters.sidecars import resolve_sidecar_path
    target_path = resolve_sidecar_path(base_path, conflict_mode)
    target_path.write_text(srt_content, encoding="utf-8")
    return target_path
