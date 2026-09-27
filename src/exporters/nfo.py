import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path
from typing import Dict, Any, Optional

from src.ai.base import VideoAnalysisResult
from src.exporters.sidecars import resolve_sidecar_path

def xml_escape(text: str) -> str:
    """Escape text for safe XML insertion."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

def write_nfo_sidecar(
    video_path: Path,
    result: VideoAnalysisResult,
    video_meta: Optional[Dict[str, Any]] = None,
    conflict_mode: str = "overwrite"
) -> Path:
    """
    Generate Kodi / Jellyfin / Plex / Emby compliant .nfo sidecar.
    Saved as <video_stem>.nfo adjacent to the video file.
    """
    base_path = video_path.parent / f"{video_path.stem}.nfo"
    out_path = resolve_sidecar_path(base_path, conflict_mode)

    movie = ET.Element("movie")

    # Title & Original Title
    title_el = ET.SubElement(movie, "title")
    title_el.text = result.title or video_path.stem

    orig_el = ET.SubElement(movie, "originaltitle")
    orig_el.text = video_path.name

    sort_el = ET.SubElement(movie, "sorttitle")
    sort_el.text = result.title or video_path.stem

    # Summary & Plot
    plot_el = ET.SubElement(movie, "plot")
    plot_el.text = result.summary

    if result.summary:
        outline_el = ET.SubElement(movie, "outline")
        outline_text = result.summary.split(". ")[0]
        outline_el.text = outline_text + ("." if not outline_text.endswith(".") else "")

    # Date / Premiere
    if video_meta and video_meta.get("creation_time"):
        c_time = str(video_meta["creation_time"])
        date_part = c_time.split("T")[0] if "T" in c_time else c_time[:10]
        premiered_el = ET.SubElement(movie, "premiered")
        premiered_el.text = date_part
        if len(date_part) >= 4 and date_part[:4].isdigit():
            year_el = ET.SubElement(movie, "year")
            year_el.text = date_part[:4]

    # Tags / Keywords
    all_tags = list(result.tags)
    for obj in result.objects:
        if obj.lower() not in [t.lower() for t in all_tags]:
            all_tags.append(obj)
    for anim in result.animals_or_pets:
        if anim.lower() not in [t.lower() for t in all_tags]:
            all_tags.append(anim)

    for tag in all_tags:
        t_el = ET.SubElement(movie, "tag")
        t_el.text = tag

    # People / Actors (Subjects)
    for person in result.people_or_subjects:
        actor_el = ET.SubElement(movie, "actor")
        name_el = ET.SubElement(actor_el, "name")
        name_el.text = person
        role_el = ET.SubElement(actor_el, "role")
        role_el.text = "Subject"

    # Animals / Pets
    for anim in result.animals_or_pets:
        actor_el = ET.SubElement(movie, "actor")
        name_el = ET.SubElement(actor_el, "name")
        name_el.text = anim
        role_el = ET.SubElement(actor_el, "role")
        role_el.text = "Pet / Animal"

    # Technical Stream details
    if video_meta:
        duration_sec = int(round(video_meta.get("duration", 0)))
        if duration_sec > 0:
            dur_el = ET.SubElement(movie, "durationinseconds")
            dur_el.text = str(duration_sec)

        fileinfo_el = ET.SubElement(movie, "fileinfo")
        streamdetails_el = ET.SubElement(fileinfo_el, "streamdetails")

        video_stream_el = ET.SubElement(streamdetails_el, "video")
        if video_meta.get("video_codec"):
            vcodec_el = ET.SubElement(video_stream_el, "codec")
            vcodec_el.text = str(video_meta["video_codec"])
        if video_meta.get("width"):
            w_el = ET.SubElement(video_stream_el, "width")
            w_el.text = str(video_meta["width"])
        if video_meta.get("height"):
            h_el = ET.SubElement(video_stream_el, "height")
            h_el.text = str(video_meta["height"])
        if duration_sec > 0:
            sdur_el = ET.SubElement(video_stream_el, "durationinseconds")
            sdur_el.text = str(duration_sec)

        if video_meta.get("has_audio") and video_meta.get("audio_codec"):
            audio_stream_el = ET.SubElement(streamdetails_el, "audio")
            acodec_el = ET.SubElement(audio_stream_el, "codec")
            acodec_el.text = str(video_meta["audio_codec"])

    # Pretty-print XML with XML declaration
    rough_string = ET.tostring(movie, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    cleaned_lines = [line for line in pretty_xml.splitlines() if line.strip()]
    output_xml = "\n".join(cleaned_lines) + "\n"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_xml)

    return out_path
