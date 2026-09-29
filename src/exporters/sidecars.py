import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from src.ai.base import VideoAnalysisResult
from src.media.probe import SUPPORTED_EXTENSIONS

def resolve_sidecar_path(target_path: Path, conflict_mode: str = "overwrite") -> Path:
    """
    If conflict_mode == 'enumerate' and target_path exists:
    Append zero-padded serialized numerator (_01, _02, etc.) to keep existing sidecars intact.
    If conflict_mode == 'overwrite': returns target_path directly.
    """
    if conflict_mode != "enumerate" or not target_path.exists():
        return target_path

    parent = target_path.parent
    name = target_path.name

    if name.endswith(".info.json"):
        prefix = name[:-10]
        ext = ".info.json"
    elif any(name.lower().endswith(f"{v_ext}.txt") for v_ext in SUPPORTED_EXTENSIONS):
        dot_idx = name.rfind(".", 0, name.rfind("."))
        prefix = name[:dot_idx]
        ext = name[dot_idx:]
    elif any(name.lower().endswith(f"{v_ext}.edl") for v_ext in SUPPORTED_EXTENSIONS):
        dot_idx = name.rfind(".", 0, name.rfind("."))
        prefix = name[:dot_idx]
        ext = name[dot_idx:]
    else:
        prefix = target_path.stem
        ext = target_path.suffix

    counter = 1
    while (parent / f"{prefix}_{counter:02d}{ext}").exists():
        counter += 1
    return parent / f"{prefix}_{counter:02d}{ext}"

def write_txt_sidecar(
    video_path: Path,
    result: VideoAnalysisResult,
    video_meta: Optional[Dict[str, Any]] = None,
    conflict_mode: str = "overwrite"
) -> Path:
    """
    Write standard .mp4.txt description sidecar.
    Format:
    [Title / Lead line]
    [Summary]
    [Timestamps]
    ---
    source: filename.mp4
    uuid: ...
    processed: ...
    provider: ...
    model: ...
    """
    base_path = video_path.parent / f"{video_path.name}.txt"
    out_path = resolve_sidecar_path(base_path, conflict_mode)
    lines = []

    # Title & Summary
    lines.append(f"{video_path.name} — {result.title}")
    lines.append("")
    lines.append(result.summary)
    lines.append("")

    # Events
    if result.events:
        lines.append("Key Moments:")
        for ev in result.events:
            star = "★ " if ev.is_highlight else "  "
            lines.append(f"{star}{ev.timecode}  {ev.description}")
        lines.append("")

    # Transcript snippet if present
    if result.audio_transcript:
        lines.append("Dialogue / Audio:")
        lines.append(f"\"{result.audio_transcript}\"")
        lines.append("")

    # Tags & Subjects
    if result.people_or_subjects:
        lines.append(f"People: {', '.join(result.people_or_subjects)}")
    if result.animals_or_pets:
        lines.append(f"Animals/Pets: {', '.join(result.animals_or_pets)}")
    if result.objects:
        lines.append(f"Objects: {', '.join(result.objects)}")
    if result.tags:
        lines.append(f"Tags: {', '.join(result.tags)}")
    lines.append("")

    # Metadata footer
    lines.append("---")
    lines.append(f"source: {video_path.name}")
    lines.append(f"uuid: {uuid.uuid4()}")
    lines.append(f"processed: {datetime.now().isoformat()}")
    lines.append(f"provider: {result.provider_name or 'unknown'}")
    lines.append(f"model: {result.model_name or 'unknown'}")
    if video_meta:
        lines.append(f"duration: {video_meta.get('duration', 0):.1f}s")
        lines.append(f"resolution: {video_meta.get('width', 0)}x{video_meta.get('height', 0)}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return out_path

def write_info_json_sidecar(
    video_path: Path,
    result: VideoAnalysisResult,
    video_meta: Optional[Dict[str, Any]] = None,
    conflict_mode: str = "overwrite"
) -> Path:
    """Write comprehensive .info.json sidecar for programmatic ingestion."""
    base_path = video_path.parent / f"{video_path.stem}.info.json"
    out_path = resolve_sidecar_path(base_path, conflict_mode)

    data = {
        "version": "1.0",
        "file": {
            "name": video_path.name,
            "path": str(video_path),
            "size_bytes": video_path.stat().st_size,
            "metadata": video_meta or {}
        },
        "analysis": {
            "title": result.title,
            "summary": result.summary,
            "events": [ev.model_dump() for ev in result.events],
            "tags": result.tags,
            "people_or_subjects": result.people_or_subjects,
            "animals_or_pets": result.animals_or_pets,
            "objects": result.objects,
            "suggested_filename": result.suggested_filename,
            "audio_transcript": result.audio_transcript,
            "provider": result.provider_name,
            "model": result.model_name,
            "processed_at": datetime.now().isoformat()
        }
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return out_path

def write_xmp_sidecar(
    video_path: Path,
    result: VideoAnalysisResult,
    video_meta: Optional[Dict[str, Any]] = None,
    conflict_mode: str = "overwrite"
) -> Path:
    """Write standard Adobe XMP sidecar for DAM tools, DigiKam, and photo organizers."""
    base_path = video_path.parent / f"{video_path.stem}.xmp"
    out_path = resolve_sidecar_path(base_path, conflict_mode)

    date_str = datetime.now().isoformat()
    if video_meta and video_meta.get("creation_time"):
        date_str = str(video_meta["creation_time"])

    # Build dc:subject bag for tags, people, animals, and objects
    combined_tags = list(result.tags)
    for p in result.people_or_subjects:
        combined_tags.append(f"Person:{p}")
    for a in result.animals_or_pets:
        combined_tags.append(f"Animal:{a}")
    for o in result.objects:
        combined_tags.append(f"Object:{o}")

    tag_elements = "\n".join([f"          <rdf:li>{xml_escape(t)}</rdf:li>" for t in combined_tags])
    person_elements = "\n".join([f"          <rdf:li>{xml_escape(p)}</rdf:li>" for p in result.people_or_subjects])

    person_block = ""
    if result.people_or_subjects:
        person_block = f"""   <Iptc4xmpExt:PersonInImage>
    <rdf:Bag>
{person_elements}
    </rdf:Bag>
   </Iptc4xmpExt:PersonInImage>
"""

    xmp_content = f"""<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
   <dc:title>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xml_escape(result.title)}</rdf:li>
    </rdf:Alt>
   </dc:title>
   <dc:description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{xml_escape(result.summary)}</rdf:li>
    </rdf:Alt>
   </dc:description>
   <dc:subject>
    <rdf:Bag>
{tag_elements}
    </rdf:Bag>
   </dc:subject>
{person_block}   <photoshop:DateCreated>{date_str}</photoshop:DateCreated>
   <xmp:CreateDate>{date_str}</xmp:CreateDate>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xmp_content)

    return out_path

def xml_escape(text: str) -> str:
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
