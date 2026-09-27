from pathlib import Path
from typing import List
from src.ai.base import TimestampEvent
from src.exporters.sidecars import resolve_sidecar_path

def parse_timecode_to_frames(timecode_str: str, fps: int = 24) -> int:
    """Convert HH:MM:SS or MM:SS to frame count."""
    parts = timecode_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = map(float, parts)
    elif len(parts) == 2:
        h = 0
        m, s = map(float, parts)
    else:
        h, m, s = 0, 0, float(parts[0] or 0)

    total_secs = h * 3600 + m * 60 + s
    return int(round(total_secs * fps))

def frames_to_smpte(frames: int, fps: int = 24) -> str:
    """Format frame count to SMPTE timecode (HH:MM:SS:FF)."""
    f = frames % fps
    total_secs = frames // fps
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

def write_edl_markers(
    video_path: Path,
    events: List[TimestampEvent],
    fps: int = 24,
    conflict_mode: str = "overwrite"
) -> Path:
    """Write CMX 3600 EDL marker file for DaVinci Resolve."""
    base_path = video_path.parent / f"{video_path.name}.edl"
    out_path = resolve_sidecar_path(base_path, conflict_mode)
    lines = [
        "TITLE: VIDEO_MARKERS",
        "FCM: NON-DROP FRAME",
        ""
    ]

    event_num = 1
    for ev in events:
        start_frame = parse_timecode_to_frames(ev.timecode, fps)
        end_frame = start_frame + fps  # 1 second duration
        tc_in = frames_to_smpte(start_frame, fps)
        tc_out = frames_to_smpte(end_frame, fps)

        # EDL Event line
        lines.append(f"{event_num:03d}  AX       V     C        {tc_in} {tc_out} {tc_in} {tc_out}")
        # DaVinci Resolve Marker notation
        color = "Green" if ev.is_highlight else "Blue"
        lines.append(f" |C:ResolveColor{color} |M:{ev.description} |D:1")
        lines.append("")
        event_num += 1

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return out_path
