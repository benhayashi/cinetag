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

    # Accompanying .srt check
    from src.media.subtitles import find_accompanying_srt
    acc_srt = find_accompanying_srt(video_path)

    # Accompanying Sony camera XML check
    from src.media.sony_xml import find_sony_xml_sidecar, parse_sony_xml
    sony_xml_path = find_sony_xml_sidecar(video_path)
    sony_meta = parse_sony_xml(sony_xml_path) if sony_xml_path else None

    # Check Sony XML GPS
    from src.media.location import parse_iso6709, reverse_geocode
    fallback_gps = None
    fallback_loc = None
    if sony_meta and sony_meta.get("gps"):
        try:
            s_lat = float(sony_meta["gps"]["latitude"])
            s_lon = float(sony_meta["gps"]["longitude"])
            fallback_gps = (s_lat, s_lon)
            fallback_loc = reverse_geocode(s_lat, s_lon, allow_online=False)
            if fallback_loc:
                fallback_loc["source"] = "sony_xml"
        except (ValueError, TypeError):
            pass

    # Determine default creation time (prioritizing Sony XML camera timestamp)
    default_creation_time = datetime.fromtimestamp(stat.st_ctime).isoformat()
    if sony_meta and sony_meta.get("creation_date"):
        default_creation_time = sony_meta["creation_date"]

    fallback_meta = {
        "path": str(video_path),
        "filename": video_path.name,
        "extension": video_path.suffix.lower(),
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "creation_time": default_creation_time,
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "video_codec": "unknown",
        "audio_codec": None,
        "has_audio": False,
        "has_subtitles": acc_srt is not None,
        "has_external_srt": acc_srt is not None,
        "external_srt_path": str(acc_srt.resolve()) if acc_srt else None,
        "embedded_subtitles_count": 0,
        "has_sony_xml": sony_xml_path is not None,
        "sony_xml_path": str(sony_xml_path.resolve()) if sony_xml_path else None,
        "sony_metadata": sony_meta,
        "camera_make": sony_meta.get("camera_make") if sony_meta else None,
        "camera_model": sony_meta.get("camera_model") if sony_meta else None,
        "capture_fps": sony_meta.get("capture_fps") if sony_meta else None,
        "has_gps": fallback_gps is not None,
        "gps_latitude": fallback_gps[0] if fallback_gps else None,
        "gps_longitude": fallback_gps[1] if fallback_gps else None,
        "location": fallback_loc,
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

    # Accompanying Sony camera XML check
    from src.media.sony_xml import find_sony_xml_sidecar, parse_sony_xml
    sony_xml_path = find_sony_xml_sidecar(video_path)
    sony_meta = parse_sony_xml(sony_xml_path) if sony_xml_path else None

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

    # Determine best date: Sony XML sidecar has exact camera timestamp with timezone
    if sony_meta and sony_meta.get("creation_date"):
        date_val = sony_meta["creation_date"]
    else:
        creation_str = tags.get("creation_time") or tags.get("date")
        if creation_str:
            date_val = creation_str
        else:
            date_val = datetime.fromtimestamp(stat.st_mtime).isoformat()

    # Check GPS coordinates from Sony XML or QuickTime container atoms
    gps_coords = None
    gps_source = None
    if sony_meta and sony_meta.get("gps"):
        try:
            s_lat = float(sony_meta["gps"]["latitude"])
            s_lon = float(sony_meta["gps"]["longitude"])
            gps_coords = (s_lat, s_lon)
            gps_source = "sony_xml"
        except (ValueError, TypeError):
            pass

    if not gps_coords and tags:
        for loc_key in ("location", "location-eng", "com.apple.quicktime.location.ISO6709", "©xyz", "xyz"):
            val = tags.get(loc_key)
            if val:
                parsed = parse_iso6709(str(val))
                if parsed:
                    gps_coords = parsed
                    gps_source = "quicktime_atom"
                    break

    location_data = None
    if gps_coords:
        location_data = reverse_geocode(gps_coords[0], gps_coords[1], allow_online=False)
        if location_data:
            location_data["source"] = gps_source

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
        "has_sony_xml": sony_xml_path is not None,
        "sony_xml_path": str(sony_xml_path.resolve()) if sony_xml_path else None,
        "sony_metadata": sony_meta,
        "camera_make": sony_meta.get("camera_make") if sony_meta else None,
        "camera_model": sony_meta.get("camera_model") if sony_meta else None,
        "capture_fps": sony_meta.get("capture_fps") if sony_meta else None,
        "has_gps": gps_coords is not None,
        "gps_latitude": gps_coords[0] if gps_coords else None,
        "gps_longitude": gps_coords[1] if gps_coords else None,
        "location": location_data,
        "creation_time": date_val,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "ffprobe_available": True,
        "tags": tags
    }
