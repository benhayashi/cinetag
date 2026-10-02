import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.core.paths import get_history_path

logger = logging.getLogger(__name__)

NUMBER_WORDS_MAP = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90",
    "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th"
}

def normalize_title_acronyms_and_numbers(text: str) -> str:
    """
    Replace written numbers with digits and common phrases with standard acronyms/abbreviations
    to save character space in titles, labels, and filenames.
    Examples:
      - 'Three Boys Playing' -> '3 Boys Playing'
      - '3-year-old girl' / 'three year old' -> '3yo girl'
      - 'United States of America' -> 'USA'
      - 'New York City' -> 'NYC'
    """
    if not text:
        return text

    res = text

    # 1. Convert written number words to digits (case-insensitive with word boundaries)
    for word, digit in NUMBER_WORDS_MAP.items():
        res = re.sub(rf'\b{word}\b', digit, res, flags=re.IGNORECASE)

    # 2. Convert age phrases: e.g. "3-year-old", "3 year old", "3 years old", "3 yrs old" -> "3yo"
    res = re.sub(r'(?i)\b(\d+)\s*[-_ ]\s*years?[-_ ]\s*old\b', r'\1yo', res)
    res = re.sub(r'(?i)\b(\d+)\s*[-_ ]\s*yrs?[-_ ]\s*old\b', r'\1yo', res)
    res = re.sub(r'(?i)\b(\d+)\s*years?[-_ ]\s*old\b', r'\1yo', res)
    res = re.sub(r'(?i)\b(\d+)\s*yrs?[-_ ]\s*old\b', r'\1yo', res)
    res = re.sub(r'(?i)\b(\d+)\s*y[./]?o\.?\b', r'\1yo', res)

    # 3. Convert common geographic & descriptive acronyms
    res = re.sub(r'(?i)\bUnited States of America\b', 'USA', res)
    res = re.sub(r'(?i)\bUnited States\b', 'USA', res)
    res = re.sub(r'(?i)\bUnited Kingdom\b', 'UK', res)
    res = re.sub(r'(?i)\bNew York City\b', 'NYC', res)
    res = re.sub(r'(?i)\bLos Angeles\b', 'LA', res)
    res = re.sub(r'(?i)\bSan Francisco\b', 'SF', res)

    return res

def truncate_at_word_boundary(text: str, max_length: int, delimiter: str = "_") -> str:
    """
    Truncate text up to max_length while breaking cleanly at word boundaries
    (e.g. delimiters like '_', '-', or space), preventing titles from ending in half-words.
    """
    if not text or max_length <= 0 or len(text) <= max_length:
        return text

    chunk = text[:max_length]
    # If the boundary character right at max_length in original text was a delimiter,
    # chunk already cleanly ends on a whole word.
    if len(text) > max_length and text[max_length] in (delimiter, "_", "-", " ", "."):
        return chunk.rstrip(" ._-")

    # Search backwards for the nearest delimiter in chunk
    last_delim = -1
    for d in (delimiter, "_", "-", " "):
        pos = chunk.rfind(d)
        if pos > last_delim:
            last_delim = pos

    # If a boundary delimiter was found at or after index 3 (or at least 25% of max_length),
    # break at that word boundary.
    if last_delim >= 3 or (max_length <= 10 and last_delim >= 1):
        return chunk[:last_delim].rstrip(" ._-")

    # Fallback to hard slice if no word boundary is found
    return chunk.rstrip(" ._-")

def sanitize_filename(name: str) -> str:
    """Sanitize string to be safe across Windows, Linux, and macOS filesystems."""
    # Replace illegal filesystem characters: / \ : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    # Replace multiple spaces/underscores with single underscore
    cleaned = re.sub(r'[\s_]+', "_", cleaned)
    # Strip leading/trailing dots or underscores
    cleaned = cleaned.strip(" ._-")
    # Limit length at word boundary
    if len(cleaned) > 100:
        cleaned = truncate_at_word_boundary(cleaned, 100)
    return cleaned or "unnamed_video"

def extract_datetime_from_filename(name: str) -> Optional[datetime]:
    """
    Extract date and optional time from common camera/phone/recorder filename conventions:
    - YYYYMMDD_HHMMSS (e.g. 20150522_230949_001.mp4, VID_20150522_230949.mp4)
    - YYYY-MM-DD_HH-MM-SS or YYYY-MM-DD HH.MM.SS
    - YYYYMMDD-HHMMSS
    - YYYYMMDD or YYYY-MM-DD
    """
    if not name:
        return None
    stem = re.sub(r"\.[^.]+$", "", Path(name).name)

    # 1. YYYYMMDD_HHMMSS or YYYYMMDD-HHMMSS or YYYYMMDDHHMMSS
    m = re.search(r"(?:^|[^\d])(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_-]?([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?:[^\d]|$)", stem)
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        try:
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            pass

    # 2. YYYY-MM-DD with optional HH:MM:SS / HH-MM-SS / HH.MM.SS
    m = re.search(r"(?:^|[^\d])(19\d\d|20\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?:[ _-]?([01]\d|2[0-3])[:.-]?([0-5]\d)[:.-]?([0-5]\d))?(?:[^\d]|$)", stem)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        s = int(m.group(6)) if m.group(6) else 0
        try:
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            pass

    # 3. YYYYMMDD without time
    m = re.search(r"(?:^|[^\d])(19[7-9]\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[^\d]|$)", stem)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime(y, mo, d, 0, 0, 0)
        except ValueError:
            pass

    return None

def resolve_datetime(
    original_path: Optional[Path] = None,
    creation_date: Optional[str] = None,
    date_override: Optional[str] = None,
    date_source: str = "smart",
    original_filename: Optional[str] = None
) -> Tuple[datetime, datetime, str]:
    """
    Resolves local and UTC datetime for filename and tag generation.
    Returns: (dt_local, dt_utc, source_used)
    where source_used is 'override', 'filename', 'metadata', or 'file_stat'.
    """
    from datetime import timezone

    # 1. Manual date override takes highest priority if explicitly supplied
    if date_override and str(date_override).strip():
        val = str(date_override).strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d", "%Y%m%d_%H%M%S", "%Y%m%d-%H%M%S", "%Y%m%d"
        ):
            try:
                dt_p = datetime.strptime(val.replace("Z", "+0000"), fmt)
                if dt_p.tzinfo is not None:
                    return dt_p, dt_p.astimezone(timezone.utc), "override"
                else:
                    return dt_p, dt_p.replace(tzinfo=timezone.utc), "override"
            except Exception:
                pass
        try:
            dt_p = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt_p.tzinfo is not None:
                return dt_p, dt_p.astimezone(timezone.utc), "override"
            else:
                return dt_p, dt_p.replace(tzinfo=timezone.utc), "override"
        except Exception:
            logger.warning(f"Could not parse date_override: '{date_override}'")

    # Candidates for filename extraction
    names_to_test = []
    if original_filename and str(original_filename).strip():
        names_to_test.append(str(original_filename).strip())
    if original_path and original_path.name:
        names_to_test.append(original_path.name)

    dt_from_file: Optional[datetime] = None
    for name_candidate in names_to_test:
        dt_from_file = extract_datetime_from_filename(name_candidate)
        if dt_from_file:
            break

    # Parse creation_date metadata if available
    dt_meta: Optional[datetime] = None
    dt_meta_utc: Optional[datetime] = None
    if creation_date:
        try:
            iso_str = str(creation_date).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso_str)
            if parsed.tzinfo is not None:
                dt_meta_utc = parsed.astimezone(timezone.utc)
                dt_meta = parsed
            else:
                dt_meta_utc = parsed.replace(tzinfo=timezone.utc)
                dt_meta = parsed
        except Exception:
            pass

    # Evaluate based on date_source
    if date_source == "filename":
        if dt_from_file:
            return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"
        if dt_meta:
            return dt_meta, dt_meta_utc or dt_meta.replace(tzinfo=timezone.utc), "metadata"

    elif date_source == "metadata":
        if dt_meta:
            return dt_meta, dt_meta_utc or dt_meta.replace(tzinfo=timezone.utc), "metadata"
        if dt_from_file:
            return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"

    else:
        # "smart" (default)
        if dt_from_file:
            if not dt_meta:
                return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"
            # Camera battery loss or reset to e.g. 2004, 1970
            if dt_meta.year <= 2005 and dt_from_file.year >= 2006:
                return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"
            # If filename contains full date & time (hour/min/sec), prefer filename timestamp
            if dt_from_file.hour != 0 or dt_from_file.minute != 0 or dt_from_file.second != 0:
                return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"
            # Otherwise use filename date
            return dt_from_file, dt_from_file.replace(tzinfo=timezone.utc), "filename"

        if dt_meta:
            return dt_meta, dt_meta_utc or dt_meta.replace(tzinfo=timezone.utc), "metadata"

    # Fallback to filesystem stat mtime if original_path exists
    if original_path and original_path.exists():
        try:
            stat = original_path.stat()
            dt_loc = datetime.fromtimestamp(stat.st_mtime)
            dt_u = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            return dt_loc, dt_u, "file_stat"
        except Exception:
            pass

    fallback_dt = datetime(1970, 1, 1, 0, 0, 0)
    return fallback_dt, fallback_dt.replace(tzinfo=timezone.utc), "fallback"

def generate_suggested_name(
    original_path: Path,
    ai_title: str,
    creation_date: Optional[str] = None,
    template: str = "{date}_{title}",
    suggested_slug: Optional[str] = None,
    collection_name: Optional[str] = None,
    people_names: Optional[List[str]] = None,
    max_title_length: int = 0,
    include_names_in_title: bool = False,
    date_override: Optional[str] = None,
    date_source: str = "smart",
    original_filename: Optional[str] = None
) -> str:
    """
    Generate a suggested filename based on metadata and a template.
    Template variables: 
      {date} (YYYY-MM-DD), {date_compact} (YYYYMMDD), 
      {year}, {month}, {day},
      {time} (HHMMSS), {time_dashed} (HH-MM-SS), 
      {time_zulu} (HHMMSS UTC), {time_zulu_dashed} (HH-MM-SS UTC),
      {title}, {names}, {people}, {original}, {folder}, {collection}, {ai_slug}
    """
    normalized_title = normalize_title_acronyms_and_numbers(ai_title)
    clean_title = sanitize_filename(normalized_title)
    if max_title_length > 0 and len(clean_title) > max_title_length:
        clean_title = truncate_at_word_boundary(clean_title, max_title_length)
    clean_original = sanitize_filename(original_path.stem)
    normalized_slug = normalize_title_acronyms_and_numbers(suggested_slug or ai_title)
    clean_slug = sanitize_filename(normalized_slug)
    if max_title_length > 0 and len(clean_slug) > max_title_length:
        clean_slug = truncate_at_word_boundary(clean_slug, max_title_length)
    
    # Process recognized people names
    names_list = []
    if people_names:
        for p in people_names:
            if not p:
                continue
            cleaned_p = sanitize_filename(p)
            if cleaned_p and cleaned_p not in names_list:
                names_list.append(cleaned_p)
    names_str = "_".join(names_list) if names_list else ""

    # If include_names_in_title is requested and template doesn't explicitly use {names} or {people}
    if include_names_in_title and names_str and ("{names}" not in template and "{people}" not in template):
        clean_title = f"{names_str}_{clean_title}"
    
    # Folder / collection name
    folder = collection_name or (original_path.parent.name if original_path.parent else "")
    clean_folder = sanitize_filename(folder)

    # Parse and resolve date and time using priority rules / overrides
    dt_local, dt_utc, _ = resolve_datetime(
        original_path=original_path,
        creation_date=creation_date,
        date_override=date_override,
        date_source=date_source,
        original_filename=original_filename
    )

    date_str = dt_local.strftime("%Y-%m-%d")
    date_compact = dt_local.strftime("%Y%m%d")
    year_str = dt_local.strftime("%Y")
    month_str = dt_local.strftime("%m")
    day_str = dt_local.strftime("%d")

    time_str = dt_local.strftime("%H%M%S")
    time_dashed = dt_local.strftime("%H-%M-%S")
    time_zulu = dt_utc.strftime("%H%M%S")
    time_zulu_dashed = dt_utc.strftime("%H-%M-%S")

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    subs = SafeDict({
        "date": date_str,
        "date_compact": date_compact,
        "year": year_str,
        "month": month_str,
        "day": day_str,
        "time": time_str,
        "time_compact": time_str,
        "time_dashed": time_dashed,
        "time_zulu": time_zulu,
        "time_zulu_dashed": time_zulu_dashed,
        "title": clean_title,
        "names": names_str,
        "people": names_str,
        "original": clean_original,
        "folder": clean_folder,
        "collection": clean_folder,
        "ai_slug": clean_slug
    })

    try:
        new_stem = template.format_map(subs)
    except Exception:
        new_stem = f"{date_compact}_{clean_title}"

    # Clean double underscores or orphaned separators if names was empty
    new_stem = re.sub(r'__+', '_', new_stem).strip(" ._-")
    new_stem = sanitize_filename(new_stem)
    return f"{new_stem}{original_path.suffix.lower()}"

def resolve_unique_rename_target(
    original_path: Path,
    desired_filename: str,
    reserved_paths: Optional[Set[Path]] = None
) -> Tuple[Path, List[Tuple[Path, Path]]]:
    """
    Safely resolves a unique target path and corresponding sidecar rename mapping.
    Ensures that neither the video file nor any accompanying sidecar files will ever
    overwrite an existing file on disk. If conflicts exist with another video or sidecar,
    it automatically enumerates with serialized zero-padded numerators (_01, _02, etc.).
    Returns: (target_path, sidecar_renames) where sidecar_renames is [(existing_sidecar, new_sidecar), ...].
    """
    parent = original_path.parent
    desired_path = parent / desired_filename
    ext = desired_path.suffix
    base_stem = desired_path.stem
    orig_resolved = original_path.resolve() if original_path.exists() else original_path
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv"}

    # 1. Discover existing sidecars belonging to original_path
    existing_sidecars: List[Tuple[Path, str, str]] = []
    if parent.exists() and original_path.exists():
        old_stem = original_path.stem
        old_name = original_path.name
        seen = set()
        for candidate in parent.iterdir():
            if not candidate.is_file() or candidate.resolve() == orig_resolved or candidate in seen:
                continue
            if candidate.suffix.lower() in VIDEO_EXTENSIONS:
                continue
            cand_name = candidate.name
            if cand_name.startswith(old_name):
                suffix_part = cand_name[len(old_name):]
                existing_sidecars.append((candidate, "name", suffix_part))
                seen.add(candidate)
            elif cand_name.startswith(f"{old_stem}."):
                suffix_part = cand_name[len(old_stem):]
                existing_sidecars.append((candidate, "stem", suffix_part))
                seen.add(candidate)

    # 2. Check if desired_path is already original_path
    if desired_path.exists() and desired_path.resolve() == orig_resolved:
        return desired_path, [(cand, cand) for cand, _, _ in existing_sidecars]

    orig_sidecar_resolved = {c[0].resolve() for c in existing_sidecars}
    standard_suffixes = [".info.json", ".srt", ".txt", f"{ext}.txt", ".nfo", ".xmp", ".edl", ".fcpxml"]

    def has_conflict(test_stem: str) -> bool:
        test_video = parent / f"{test_stem}{ext}"
        # Direct video conflict
        if test_video.exists() and test_video.resolve() != orig_resolved:
            return True
        if reserved_paths and test_video in reserved_paths:
            return True

        # Video stem conflict with other video formats in same folder
        if parent.exists():
            for f in parent.iterdir():
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS and f.resolve() != orig_resolved:
                    if f.stem == test_stem:
                        return True

        # Conflict with projected sidecars of original_path
        for cand_file, mode, suffix_part in existing_sidecars:
            if mode == "name":
                proj_s = parent / f"{test_stem}{ext}{suffix_part}"
            else:
                proj_s = parent / f"{test_stem}{suffix_part}"
            if proj_s.exists() and proj_s.resolve() != cand_file.resolve():
                return True
            if reserved_paths and proj_s in reserved_paths:
                return True

        # Conflict with standard sidecars that already exist on disk
        for s_suf in standard_suffixes:
            proj_check = parent / f"{test_stem}{s_suf}"
            if proj_check.exists() and proj_check.resolve() not in orig_sidecar_resolved:
                return True
            if reserved_paths and proj_check in reserved_paths:
                return True

        return False

    if not has_conflict(base_stem):
        final_stem = base_stem
    else:
        # Enumerate with _01, _02, etc.
        match = re.search(r'^(.*)_(\d+)$', base_stem)
        if match:
            prefix = match.group(1)
            counter = int(match.group(2)) + 1
            width = max(2, len(match.group(2)))
        else:
            prefix = base_stem
            counter = 1
            width = 2

        while True:
            cand_stem = f"{prefix}_{counter:0{width}d}"
            if not has_conflict(cand_stem):
                final_stem = cand_stem
                break
            counter += 1

    target_path = parent / f"{final_stem}{ext}"
    sidecar_renames = []
    for cand_file, mode, suffix_part in existing_sidecars:
        if mode == "name":
            new_s = parent / f"{target_path.name}{suffix_part}"
        else:
            new_s = parent / f"{final_stem}{suffix_part}"
        sidecar_renames.append((cand_file, new_s))

    if reserved_paths is not None:
        reserved_paths.add(target_path)
        for _, new_s in sidecar_renames:
            reserved_paths.add(new_s)

    return target_path, sidecar_renames


def execute_rename(
    original_path: Path,
    new_filename: str,
    rename_sidecars: bool = True,
    new_creation_date: Optional[str] = None,
    new_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Safely rename a video and its accompanying sidecar files with collision checks.
    Logs the operation to history for 1-click rollback.
    Uses zero-padded serialized numerators (_01, _02, etc.) if target filename already exists.
    """
    if not original_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {original_path}")

    target_path, candidate_sidecars = resolve_unique_rename_target(original_path, new_filename)

    if target_path == original_path:
        # If target filename is identical but new_title is provided, update sidecar metadata
        if new_title:
            for candidate, _ in candidate_sidecars:
                cand_name = candidate.name
                if cand_name.endswith(".info.json"):
                    try:
                        with open(candidate, "r", encoding="utf-8") as jf:
                            jdata = json.load(jf)
                        if "analysis" in jdata and isinstance(jdata["analysis"], dict):
                            jdata["analysis"]["title"] = new_title
                        with open(candidate, "w", encoding="utf-8") as jf:
                            json.dump(jdata, jf, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                elif cand_name.endswith(".txt"):
                    try:
                        content = candidate.read_text(encoding="utf-8")
                        lines = content.splitlines()
                        if lines and ("—" in lines[0] or " - " in lines[0]):
                            lines[0] = f"{target_path.name} — {new_title}"
                            candidate.write_text("\n".join(lines), encoding="utf-8")
                    except Exception:
                        pass
                elif cand_name.endswith(".nfo"):
                    try:
                        content = candidate.read_text(encoding="utf-8")
                        if "<title>" in content:
                            content = re.sub(r"<title>.*?</title>", f"<title>{new_title}</title>", content, count=1)
                            candidate.write_text(content, encoding="utf-8")
                    except Exception:
                        pass
            return {"status": "success", "original": str(original_path), "renamed_to": str(target_path), "sidecars_renamed": [], "message": "Metadata updated"}
        return {"status": "skipped", "message": "Filename is identical"}

    sidecar_renames = candidate_sidecars if rename_sidecars else []

    # Perform rename
    original_path.rename(target_path)
    sidecars_moved = []
    for old_s, new_s in sidecar_renames:
        if old_s.exists() and old_s.resolve() != new_s.resolve():
            old_s.rename(new_s)
            sidecars_moved.append({"from": str(old_s), "to": str(new_s)})

    # Update sidecar metadata in .info.json, .txt, .nfo if present
    for old_s, new_s in sidecar_renames:
        if new_s.name.endswith(".info.json") and new_s.exists():
            try:
                with open(new_s, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                if "file" in jdata and isinstance(jdata["file"], dict):
                    jdata["file"]["name"] = target_path.name
                    jdata["file"]["path"] = str(target_path)
                    if new_creation_date:
                        if "metadata" not in jdata["file"] or not isinstance(jdata["file"]["metadata"], dict):
                            jdata["file"]["metadata"] = {}
                        jdata["file"]["metadata"]["creation_time"] = new_creation_date
                if new_title and "analysis" in jdata and isinstance(jdata["analysis"], dict):
                    jdata["analysis"]["title"] = new_title
                    jdata["analysis"]["suggested_filename"] = target_path.name
                with open(new_s, "w", encoding="utf-8") as jf:
                    json.dump(jdata, jf, indent=2, ensure_ascii=False)
            except Exception as je:
                logger.warning(f"Could not update {new_s.name} metadata: {je}")

        if (new_s.name.endswith(".txt") or new_s.name.endswith(".txt.txt")) and new_s.exists() and new_title:
            try:
                content = new_s.read_text(encoding="utf-8")
                lines = content.splitlines()
                if lines and ("—" in lines[0] or " - " in lines[0]):
                    lines[0] = f"{target_path.name} — {new_title}"
                    new_s.write_text("\n".join(lines), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not update title in {new_s.name}: {e}")

        if new_s.name.endswith(".nfo") and new_s.exists() and new_title:
            try:
                content = new_s.read_text(encoding="utf-8")
                if "<title>" in content:
                    import re
                    content = re.sub(r"<title>.*?</title>", f"<title>{new_title}</title>", content, count=1)
                    new_s.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not update title in {new_s.name}: {e}")

    # Log to rename history journal
    history_file = get_history_path() / "renames.json"
    history_records = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_records = json.load(f)
        except Exception:
            history_records = []

    tx = {
        "timestamp": datetime.now().isoformat(),
        "from": str(original_path),
        "to": str(target_path),
        "sidecars": sidecars_moved
    }
    history_records.append(tx)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history_records, f, indent=2)

    return {
        "status": "success",
        "original": str(original_path),
        "renamed_to": str(target_path),
        "sidecars_renamed": sidecars_moved
    }

def undo_last_rename() -> Optional[Dict[str, Any]]:
    """Undo the most recent rename operation from the transaction log."""
    history_file = get_history_path() / "renames.json"
    if not history_file.exists():
        return None

    try:
        with open(history_file, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception:
        return None

    if not records:
        return None

    last_tx = records.pop()
    to_path = Path(last_tx["to"])
    from_path = Path(last_tx["from"])

    # Revert main file
    if to_path.exists():
        to_path.rename(from_path)

    # Revert sidecars
    for item in last_tx.get("sidecars", []):
        current = Path(item["to"])
        original = Path(item["from"])
        if current.exists():
            current.rename(original)

    # Save updated history
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    return {
        "reverted_from": str(to_path),
        "restored_to": str(from_path)
    }
