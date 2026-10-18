import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def find_sony_xml_sidecar(video_path: Path) -> Optional[Path]:
    """
    Locates any accompanying Sony camera XML sidecar file.
    Sony cameras (XAVC / Alpha series) generate files named:
    - <stem>M01.XML or <stem>M01.xml (e.g. C0001M01.XML for C0001.MP4)
    - <stem>.XML or <stem>.xml (e.g. C0001.XML)
    - <filename>.XML or <filename>.xml (e.g. C0001.MP4.XML)
    """
    if not video_path:
        return None

    parent = video_path.parent
    if not parent.exists():
        return None

    stem = video_path.stem
    name = video_path.name
    stem_lower = stem.lower()
    name_lower = name.lower()

    # Pattern for Sony M01, M02, etc. (case-insensitive)
    m_pattern = re.compile(rf"^{re.escape(stem_lower)}m\d{{2,}}\.xml$", re.IGNORECASE)

    candidates = []
    try:
        for f in parent.iterdir():
            if not f.is_file():
                continue
            f_name_lower = f.name.lower()
            if f.suffix.lower() != ".xml":
                continue

            # 1. Exact stem match: C0001.XML / C0001.xml
            if f_name_lower == f"{stem_lower}.xml":
                return f

            # 2. Sony standard M-series: C0001M01.XML / C0001M01.xml
            if m_pattern.match(f_name_lower):
                candidates.append(f)

            # 3. Full name match: C0001.MP4.xml
            elif f_name_lower == f"{name_lower}.xml":
                candidates.append(f)
    except Exception as e:
        logger.warning(f"Error searching for Sony XML sidecar for {video_path}: {e}")

    if candidates:
        # Sort so M01 comes before M02 if multiple exist
        candidates.sort(key=lambda p: p.name)
        return candidates[0]

    return None

def parse_sony_xml(xml_path: Path) -> Dict[str, Any]:
    """
    Parses a Sony NonRealTimeMeta XML sidecar file and extracts shooting metadata.
    Returns a dictionary of normalized metadata fields.
    """
    result: Dict[str, Any] = {
        "xml_path": str(xml_path.resolve()),
        "filename": xml_path.name,
        "is_sony_nrtm": False,
        "camera_make": None,
        "camera_model": None,
        "camera_serial": None,
        "creation_date": None,
        "capture_fps": None,
        "format_fps": None,
        "video_codec": None,
        "duration_frames": None,
        "audio_channels": None,
        "lens_model": None,
        "recording_mode": None,
        "gps": None,
        "summary": None
    }

    if not xml_path.exists():
        return result

    try:
        # Parse XML tree
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Check root tag or namespace
        root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""

        if root_tag == "NonRealTimeMeta" or "nonRealTimeMeta" in ns.lower():
            result["is_sony_nrtm"] = True
            result["camera_make"] = "Sony"

        # Walk elements and extract key fields by local tag name
        for elem in root.iter():
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            if local_tag == "CreationDate":
                cdate = elem.get("value")
                if cdate and not result["creation_date"]:
                    result["creation_date"] = cdate.strip()

            elif local_tag == "Device":
                mfg = elem.get("manufacturer")
                if mfg:
                    result["camera_make"] = mfg.strip()
                elif not result["camera_make"]:
                    result["camera_make"] = "Sony"
                model = elem.get("modelName")
                if model:
                    result["camera_model"] = model.strip()
                serial = elem.get("serialNo")
                if serial and serial not in ("4294967295", "0"):
                    result["camera_serial"] = serial.strip()

            elif local_tag in ("VideoFrame", "VideoFormat"):
                if elem.get("videoCodec"):
                    result["video_codec"] = elem.get("videoCodec").strip()
                if elem.get("captureFps"):
                    result["capture_fps"] = elem.get("captureFps").strip()
                if elem.get("formatFps"):
                    result["format_fps"] = elem.get("formatFps").strip()

            elif local_tag == "Duration":
                dval = elem.get("value")
                if dval:
                    try:
                        result["duration_frames"] = int(dval)
                    except ValueError:
                        pass

            elif local_tag == "AudioFormat":
                ch = elem.get("numOfChannel")
                if ch:
                    try:
                        result["audio_channels"] = int(ch)
                    except ValueError:
                        pass

            elif local_tag == "RecordingMode":
                rm = elem.get("type")
                if rm:
                    result["recording_mode"] = rm.strip()

            elif local_tag in ("LensModel", "Lens"):
                lval = elem.get("value") or (elem.text and elem.text.strip())
                if lval and not result["lens_model"]:
                    result["lens_model"] = lval.strip()

            elif local_tag == "ExifGPS":
                lat = elem.get("latitude")
                lon = elem.get("longitude")
                if lat and lon:
                    result["gps"] = {"latitude": lat, "longitude": lon}

        # Build human-readable summary
        parts = []
        if result["camera_model"]:
            mfg = result["camera_make"] or "Sony"
            if mfg.lower() in result["camera_model"].lower():
                parts.append(result["camera_model"])
            else:
                parts.append(f"{mfg} {result['camera_model']}")
        elif result["camera_make"]:
            parts.append(result["camera_make"])

        if result["capture_fps"]:
            parts.append(f"{result['capture_fps']}")
        if result["video_codec"]:
            # Simplify codec name if long (e.g. AVC_3840_2160_HP@L51 -> AVC 4K)
            vc = result["video_codec"]
            if "3840_2160" in vc:
                parts.append("4K UHD")
            elif "1920_1080" in vc:
                parts.append("1080p FHD")
            else:
                parts.append(vc)

        if result["audio_channels"]:
            parts.append(f"{result['audio_channels']}ch Audio")

        result["summary"] = " • ".join(parts) if parts else None

    except Exception as e:
        logger.warning(f"Failed to parse Sony XML sidecar {xml_path}: {e}")

    return result

def format_sony_context_prompt(sony_meta: Dict[str, Any]) -> Optional[str]:
    """
    Format Sony camera shooting metadata for inclusion in AI prompt context.
    """
    if not sony_meta:
        return None

    lines = []
    lines.append("=== Camera & Technical Shooting Context (Sony XML Sidecar) ===")
    
    cam_str = ""
    if sony_meta.get("camera_make") or sony_meta.get("camera_model"):
        make = sony_meta.get("camera_make") or "Sony"
        model = sony_meta.get("camera_model") or ""
        cam_str = f"{make} {model}".strip()
        if sony_meta.get("camera_serial"):
            cam_str += f" (Serial: {sony_meta['camera_serial']})"
        lines.append(f"Recording Device: {cam_str}")

    if sony_meta.get("creation_date"):
        lines.append(f"Recorded Date & Time: {sony_meta['creation_date']}")

    specs = []
    if sony_meta.get("capture_fps"):
        fps = sony_meta['capture_fps']
        fps_note = f"{fps} framerate"
        if "120" in fps or "100" in fps:
            fps_note += " (High frame rate / slow-motion capture)"
        elif "24" in fps or "23.98" in fps:
            fps_note += " (Cinematic 24p)"
        specs.append(fps_note)

    if sony_meta.get("video_codec"):
        specs.append(f"Codec: {sony_meta['video_codec']}")

    if sony_meta.get("audio_channels"):
        specs.append(f"{sony_meta['audio_channels']}-channel Audio")

    if specs:
        lines.append(f"Shooting Specifications: {', '.join(specs)}")

    if sony_meta.get("lens_model"):
        lines.append(f"Lens: {sony_meta['lens_model']}")

    lines.append("Instructions: Use this verified camera information to understand the recording quality, framerate context (e.g. slow motion vs real-time), and include the camera model in equipment/objects and metadata tags when appropriate.")
    lines.append("==============================================================")

    return "\n".join(lines)
