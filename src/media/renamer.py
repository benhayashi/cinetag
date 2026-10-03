import json
import logging
import os
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

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_REGEX = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember))"

CAMERA_PREFIX_RE = re.compile(
    r"^(?:VID|VIDEO|IMG|PICT|DSC|DSCF|DSCN|MOV|GOPR|GP|DJI|PXL|REC|CLIP|MVI|SAM|MAH|C\d{4})[_-]?",
    re.IGNORECASE
)
SEQUENCE_SUFFIX_RE = re.compile(
    r"[_-]?(?:\d{3,4}|\(\d+\)|\[\d+\])$"
)
GENERIC_FILENAME_WORDS = {
    "vid", "video", "mov", "movie", "clip", "dsc", "img", "pxl", "rec", "recording",
    "shot", "cut", "edit", "unnamed", "file", "media", "camera"
}

def extract_datetime_from_filename(name: str, order_preference: str = "auto") -> Optional[datetime]:
    """
    Extract date and optional time from common filename conventions:
    - YYYYMMDD_HHMMSS, YYYYMMDD-HHMMSS, or YYYYMMDDHHMMSS
    - YYYY-MM-DD or YYYY_MM_DD or YYYY.MM.DD with optional HH:MM:SS
    - Named months: July_2019, 15_Aug_2021, Oct-10-2022
    - MM-DD-YYYY or DD-MM-YYYY with optional time, resolved by order_preference ('auto' | 'mdy' | 'dmy' | 'ymd')
    - YYYYMMDD without time
    """
    if not name:
        return None
    stem = re.sub(r"\.[^.]+$", "", Path(name).name)

    # 1. YYYYMMDD_HHMMSS or YYYYMMDD-HHMMSS or YYYYMMDDHHMMSS
    m = re.search(r"(?:^|[^\d])(19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_-]?([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?:[^\d]|$)", stem)
    if m:
        try:
            return datetime(*map(int, m.groups()))
        except ValueError:
            pass

    # 2. YYYY-MM-DD or YYYY_MM_DD or YYYY.MM.DD with optional HH:MM:SS / HH-MM-SS / HH.MM.SS
    m = re.search(r"(?:^|[^\d])(19\d\d|20\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[ _-]?([01]\d|2[0-3])[:.-]?([0-5]\d)[:.-]?([0-5]\d))?(?:[^\d]|$)", stem)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            h = int(m.group(4)) if m.group(4) else 0
            mi = int(m.group(5)) if m.group(5) else 0
            s = int(m.group(6)) if m.group(6) else 0
            return datetime(y, mo, d, h, mi, s)
        except ValueError:
            pass

    # 3. Named month patterns
    # 3a. Month_DD_YYYY
    m = re.search(rf"(?:^|[^\w]){MONTH_REGEX}[-_\s]+(0?[1-9]|[12]\d|3[01])[-_,\s]+(19\d\d|20\d\d)(?:[^\d]|$)", stem, re.IGNORECASE)
    if m:
        try:
            mo = MONTH_MAP[m.group(1).lower()]
            d = int(m.group(2))
            y = int(m.group(3))
            return datetime(y, mo, d, 0, 0, 0)
        except (ValueError, KeyError):
            pass

    # 3b. DD_Month_YYYY
    m = re.search(rf"(?:^|[^\d])(0?[1-9]|[12]\d|3[01])[-_\s]+{MONTH_REGEX}[-_,\s]+(19\d\d|20\d\d)(?:[^\d]|$)", stem, re.IGNORECASE)
    if m:
        try:
            d = int(m.group(1))
            mo = MONTH_MAP[m.group(2).lower()]
            y = int(m.group(3))
            return datetime(y, mo, d, 0, 0, 0)
        except (ValueError, KeyError):
            pass

    # 3c. Month_YYYY (no day)
    m = re.search(rf"(?:^|[^\w]){MONTH_REGEX}[-_\s]+(19\d\d|20\d\d)(?:[^\d]|$)", stem, re.IGNORECASE)
    if m:
        try:
            mo = MONTH_MAP[m.group(1).lower()]
            y = int(m.group(2))
            return datetime(y, mo, 1, 0, 0, 0)
        except (ValueError, KeyError):
            pass

    # 4. Number-Number-Year (MM-DD-YYYY or DD-MM-YYYY)
    m = re.search(r"(?:^|[^\d])(0?[1-9]|[12]\d|3[01])[-_.](0?[1-9]|[12]\d|3[01])[-_.](19\d\d|20\d\d)(?:[ _-]?([01]\d|2[0-3])[:.-]?([0-5]\d)[:.-]?([0-5]\d))?(?:[^\d]|$)", stem)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        y = int(m.group(3))
        h = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        s = int(m.group(6)) if m.group(6) else 0

        pref = (order_preference or "auto").lower()
        if pref == "dmy":
            day, month = a, b
        elif pref == "mdy":
            month, day = a, b
        else:  # auto
            if a > 12 and b <= 12:
                day, month = a, b
            elif b > 12 and a <= 12:
                month, day = a, b
            else:
                # Default to US MM-DD-YYYY
                month, day = a, b
        try:
            return datetime(y, month, day, h, mi, s)
        except ValueError:
            pass

    # 5. YYYYMMDD without time
    m = re.search(r"(?:^|[^\d])(19[7-9]\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[^\d]|$)", stem)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None

def extract_filename_context(name: str, date_order: str = "auto") -> Dict[str, Any]:
    """
    Extract meaningful metadata and context clues from a video filename:
    - Detected date/time (with multi-format support: YMD, MDY, DMY, month names)
    - Cleaned title/context keywords (stripping camera prefixes like VID_, IMG_, DSC_, sequence numbers, and dates)
    - Extracted potential subject/people names or location hints
    - Indicator if meaningful textual clues exist beyond generic camera labels
    """
    if not name:
        return {
            "original_filename": "",
            "detected_date": None,
            "detected_date_str": None,
            "detected_date_formatted": None,
            "cleaned_text": "",
            "potential_names": [],
            "has_meaningful_clues": False
        }

    original_filename = Path(name).name
    stem = Path(name).stem

    # Detect date
    dt = extract_datetime_from_filename(original_filename, order_preference=date_order)
    dt_str = dt.strftime("%Y-%m-%d") if dt else None
    dt_formatted = None
    if dt:
        if dt.day != 1 or dt.hour > 0:
            dt_formatted = dt.strftime("%B %d, %Y")
        else:
            dt_formatted = dt.strftime("%B %Y")

    # Clean stem of camera prefixes and sequence suffixes
    stem_no_cam = CAMERA_PREFIX_RE.sub("", stem)
    stem_no_seq = SEQUENCE_SUFFIX_RE.sub("", stem_no_cam)

    # Strip out detected date/time patterns from text
    d_clean = re.sub(r"(?:19\d\d|20\d\d)[-_.]?(?:0[1-9]|1[0-2])[-_.]?(?:0[1-9]|[12]\d|3[01])(?:[ _-]?[012]\d[:.-]?[0-5]\d[:.-]?[0-5]\d)?", "", stem_no_seq)
    d_clean = re.sub(r"(?:0?[1-9]|[12]\d|3[01])[-_.](?:0?[1-9]|[12]\d|3[01])[-_.](?:19\d\d|20\d\d)(?:[ _-]?[012]\d[:.-]?[0-5]\d[:.-]?[0-5]\d)?", "", d_clean)
    d_clean = re.sub(rf"{MONTH_REGEX}[-_\s]+(?:0?[1-9]|[12]\d|3[01])?[-_,\s]*(?:19\d\d|20\d\d)?", "", d_clean, flags=re.IGNORECASE)
    d_clean = re.sub(rf"(?:0?[1-9]|[12]\d|3[01])[-_\s]+{MONTH_REGEX}[-_,\s]*(?:19\d\d|20\d\d)?", "", d_clean, flags=re.IGNORECASE)
    d_clean = re.sub(r"(?:19\d\d|20\d\d)", "", d_clean)

    # Clean words
    raw_tokens = re.split(r"[\s_.\-+]+", d_clean)
    cleaned_tokens = [w for w in raw_tokens if w and not w.isdigit()]
    
    # Filter out generic words when checking for meaningfulness
    substantive_tokens = [w for w in cleaned_tokens if w.lower() not in GENERIC_FILENAME_WORDS and len(w) > 1]
    
    cleaned_text = " ".join(cleaned_tokens).strip()

    # Identify potential names / proper nouns / places
    stopwords = {"and", "the", "with", "at", "for", "in", "on", "of", "to", "by", "from", "a", "an", "is", "my", "our"}
    potential_names = []
    for token in substantive_tokens:
        if token[0].isupper() and token.lower() not in stopwords:
            if token not in potential_names:
                potential_names.append(token)

    has_meaningful_clues = bool(substantive_tokens and len(" ".join(substantive_tokens)) >= 3)

    return {
        "original_filename": original_filename,
        "detected_date": dt,
        "detected_date_str": dt_str,
        "detected_date_formatted": dt_formatted,
        "cleaned_text": cleaned_text,
        "potential_names": potential_names,
        "has_meaningful_clues": has_meaningful_clues
    }

def format_filename_context_prompt(info: Dict[str, Any]) -> Optional[str]:
    """
    Format extracted filename metadata into structured AI prompt guidance.
    """
    if not info:
        return None
    orig_name = info.get("original_filename", "")
    date_str = info.get("detected_date_formatted") or info.get("detected_date_str")
    cleaned_text = info.get("cleaned_text")
    potential_names = info.get("potential_names", [])
    has_meaningful_clues = info.get("has_meaningful_clues", False)

    if not has_meaningful_clues and not date_str:
        return None

    lines = [
        "=== Original Filename Context & Clues ===",
        f"Original filename: \"{orig_name}\""
    ]
    if date_str:
        lines.append(f"- Date clue from filename: {date_str}")
    if cleaned_text:
        lines.append(f"- Context/topic clues from filename: \"{cleaned_text}\"")
    if potential_names:
        lines.append(f"- Keywords/potential subjects: {', '.join(potential_names)}")

    if has_meaningful_clues:
        lines.extend([
            "",
            "Instructions for incorporating filename clues:",
            "1. Grounding & Verification: If people, activities, or locations mentioned in the filename are visible or audible in the video, prioritize including them in the title, summary, people_or_subjects, and tags.",
            "2. Direct AI Slug: Reflect key subjects and actions from both the video and filename hints in 'suggested_filename' (lowercase with underscores, e.g. \"sarah_birthday_cake\")."
        ])
    elif date_str:
        lines.extend([
            "",
            "Note: The filename contains a date clue. You may use this date context to orient the timeframe if relevant."
        ])

    lines.append("==========================================")
    return "\n".join(lines)


def resolve_datetime(
    original_path: Optional[Path] = None,
    creation_date: Optional[str] = None,
    date_override: Optional[str] = None,
    date_source: str = "smart",
    original_filename: Optional[str] = None,
    date_order: str = "auto"
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
        dt_from_file = extract_datetime_from_filename(name_candidate, order_preference=date_order)
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
    original_filename: Optional[str] = None,
    date_order: str = "auto"
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
        original_filename=original_filename,
        date_order=date_order
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

def update_file_date_and_metadata(
    video_path: Path,
    new_date: str,
    update_mtime: bool = True,
    rename_to_new_date: bool = False,
    template: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates the recorded creation date in video sidecars (.info.json, .nfo, .txt),
    optionally synchronizes the filesystem modified time (mtime via os.utime),
    and optionally renames the video and sidecars according to the new date.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Parse new_date
    dt_local, dt_utc, _ = resolve_datetime(original_path=video_path, date_override=new_date)
    iso_date = dt_local.isoformat()
    parent = video_path.parent
    stem = video_path.stem
    name = video_path.name

    sidecars_updated = []

    # 1. Update .info.json
    json_candidates = [parent / f"{stem}.info.json", parent / f"{name}.info.json"]
    for jc in json_candidates:
        if jc.exists():
            try:
                with open(jc, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                if "file" not in jdata:
                    jdata["file"] = {}
                if "metadata" not in jdata["file"]:
                    jdata["file"]["metadata"] = {}
                jdata["file"]["metadata"]["creation_time"] = iso_date
                jdata["file"]["metadata"]["date_source_used"] = "confirmed_update"
                jdata.pop("pending_date_proposal", None)
                if "analysis" in jdata and isinstance(jdata["analysis"], dict):
                    jdata["analysis"].pop("pending_date_proposal", None)
                    if "detected_date_in_context" in jdata["analysis"]:
                        jdata["analysis"]["detected_date_in_context"] = iso_date
                with open(jc, "w", encoding="utf-8") as jf:
                    json.dump(jdata, jf, indent=2, ensure_ascii=False)
                sidecars_updated.append(str(jc))
            except Exception as e:
                logger.warning(f"Error updating {jc.name}: {e}")

    # 2. Update .nfo
    nfo_candidates = [parent / f"{stem}.nfo", parent / f"{name}.nfo"]
    for nc in nfo_candidates:
        if nc.exists():
            try:
                content = nc.read_text(encoding="utf-8")
                date_str = dt_local.strftime("%Y-%m-%d")
                year_str = dt_local.strftime("%Y")
                if "<premiered>" in content:
                    content = re.sub(r"<premiered>.*?</premiered>", f"<premiered>{date_str}</premiered>", content)
                elif "<movie>" in content:
                    content = content.replace("</movie>", f"  <premiered>{date_str}</premiered>\n  <year>{year_str}</year>\n</movie>")
                if "<year>" in content:
                    content = re.sub(r"<year>.*?</year>", f"<year>{year_str}</year>", content)
                nc.write_text(content, encoding="utf-8")
                sidecars_updated.append(str(nc))
            except Exception as e:
                logger.warning(f"Error updating {nc.name}: {e}")

    # 3. Update filesystem mtime if requested
    if update_mtime:
        try:
            epoch = dt_local.timestamp()
            os.utime(video_path, (epoch, epoch))
            # Also sync any sidecars
            for sc_path_str in sidecars_updated:
                sc_p = Path(sc_path_str)
                if sc_p.exists():
                    try:
                        os.utime(sc_p, (epoch, epoch))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not update mtime for {video_path.name}: {e}")

    # 4. Optional rename to reflect new date
    renamed_to = str(video_path)
    if rename_to_new_date:
        title = stem.replace("_", " ")
        for jc in json_candidates:
            if jc.exists():
                try:
                    with open(jc, "r", encoding="utf-8") as jf:
                        title = json.load(jf).get("analysis", {}).get("title", title)
                except Exception:
                    pass

        new_fn = generate_suggested_name(
            original_path=video_path,
            ai_title=title,
            creation_date=iso_date,
            template=template or "{date_compact}_{time_zulu}_{title}",
            date_override=iso_date
        )
        if new_fn != video_path.name:
            ren_res = execute_rename(
                original_path=video_path,
                new_filename=new_fn,
                rename_sidecars=True,
                new_creation_date=iso_date
            )
            if ren_res.get("status") == "success":
                renamed_to = ren_res.get("renamed_to", str(video_path))
                if update_mtime:
                    try:
                        epoch = dt_local.timestamp()
                        os.utime(Path(renamed_to), (epoch, epoch))
                    except Exception:
                        pass

    return {
        "status": "success",
        "original_path": str(video_path),
        "final_path": renamed_to,
        "new_date": iso_date,
        "sidecars_updated": sidecars_updated
    }

def format_enumeration(index: int, total: int, style: str = "pt", pad_digits: int = 2) -> str:
    """
    Format a series enumeration suffix.
    Styles:
      - 'pt': '_pt01', '_pt02'
      - 'part': '_part01', '_part02'
      - 'numeric': '_01', '_02'
      - 'hyphen': '-01', '-02'
      - 'count': '_01_of_03', '_02_of_03'
      - 'title_part': ' (Part 1)', ' (Part 2)'
      - 'none': ''
    """
    num_str = str(index).zfill(pad_digits)
    total_str = str(total).zfill(pad_digits)
    style_norm = (style or "pt").lower().strip()

    if style_norm == "pt":
        return f"_pt{num_str}"
    elif style_norm == "part":
        return f"_part{num_str}"
    elif style_norm == "numeric":
        return f"_{num_str}"
    elif style_norm == "hyphen":
        return f"-{num_str}"
    elif style_norm == "count":
        return f"_{num_str}_of_{total_str}"
    elif style_norm in ("title_part", "title"):
        return f" (Part {index})"
    elif style_norm == "none":
        return ""
    else:
        return f"_{num_str}"

def generate_series_rename_plan(
    items: List[Dict[str, Any]],
    series_title: str,
    scheme: str = "datetime_title_enum",
    enum_style: str = "pt",
    pad_digits: int = 2,
    start_index: int = 1,
    time_strategy: str = "individual",
    date_source: str = "smart",
    date_order: str = "auto",
    rename_template: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Computes a conflict-free sequential renaming plan for multiple video items in a series.
    Each item dict should contain at least:
      - 'file_path': str or Path
      Optional:
      - 'creation_date': str
      - 'date_override': str
      - 'original_filename': str
      - 'title': str
      - 'suggested_slug': str
    """
    plan = []
    total_count = len(items)
    reserved_paths: Set[Path] = set()

    clean_series_title = sanitize_filename(normalize_title_acronyms_and_numbers(series_title.strip())) if series_title and series_title.strip() else "series"
    clean_series_slug = clean_series_title.lower()

    # Pre-resolve series start datetime if needed
    start_dt_local: Optional[datetime] = None
    start_dt_utc: Optional[datetime] = None
    if time_strategy == "series_start" and items:
        first_item = items[0]
        fp_first = Path(first_item.get("file_path", ""))
        c_date = first_item.get("creation_date")
        d_override = first_item.get("date_override")
        orig_fn = first_item.get("original_filename") or (fp_first.name if fp_first else "")
        start_dt_local, start_dt_utc, _ = resolve_datetime(
            original_path=fp_first,
            creation_date=c_date,
            date_override=d_override,
            date_source=date_source,
            original_filename=orig_fn,
            date_order=date_order
        )

    for i, it in enumerate(items):
        item_index = i + start_index
        orig_path = Path(it.get("file_path", ""))
        if not orig_path.exists():
            continue

        c_date = it.get("creation_date")
        d_override = it.get("date_override")
        orig_fn = it.get("original_filename") or orig_path.name

        if time_strategy == "series_start" and start_dt_local and start_dt_utc:
            dt_local, dt_utc = start_dt_local, start_dt_utc
        else:
            dt_local, dt_utc, _ = resolve_datetime(
                original_path=orig_path,
                creation_date=c_date,
                date_override=d_override,
                date_source=date_source,
                original_filename=orig_fn,
                date_order=date_order
            )

        date_compact = dt_local.strftime("%Y%m%d")
        date_str = dt_local.strftime("%Y-%m-%d")
        time_str = dt_local.strftime("%H%M%S")
        time_dashed = dt_local.strftime("%H-%M-%S")
        time_zulu = dt_utc.strftime("%H%M%S")
        time_zulu_dashed = dt_utc.strftime("%H-%M-%S")

        enum_str = format_enumeration(item_index, total_count + start_index - 1, style=enum_style, pad_digits=pad_digits)
        ext = orig_path.suffix.lower()

        # Build base filename according to scheme
        if scheme == "datetime_title_enum":
            stem = f"{date_compact}_{time_zulu}_{clean_series_title}{enum_str}"
        elif scheme == "date_time_title_enum":
            stem = f"{date_str}_{time_str}_{clean_series_title}{enum_str}"
        elif scheme == "date_title_enum":
            stem = f"{date_compact}_{clean_series_title}{enum_str}"
        elif scheme == "ai_slug_enum":
            stem = f"{clean_series_slug}{enum_str}"
        elif scheme == "date_ai_slug_enum":
            stem = f"{date_compact}_{clean_series_slug}{enum_str}"
        elif scheme == "title_enum":
            stem = f"{clean_series_title}{enum_str}"
        elif scheme == "custom" and rename_template:
            subs = defaultdict(str, {
                "date": date_str,
                "date_compact": date_compact,
                "year": dt_local.strftime("%Y"),
                "month": dt_local.strftime("%m"),
                "day": dt_local.strftime("%d"),
                "time": time_str,
                "time_dashed": time_dashed,
                "time_zulu": time_zulu,
                "time_zulu_dashed": time_zulu_dashed,
                "title": clean_series_title,
                "ai_slug": clean_series_slug,
                "original": sanitize_filename(orig_path.stem),
                "folder": sanitize_filename(orig_path.parent.name if orig_path.parent else ""),
                "enum": enum_str,
                "enumeration": enum_str,
                "part": str(item_index).zfill(pad_digits),
                "total": str(total_count)
            })
            try:
                stem = rename_template.format_map(subs)
                if "{enum}" not in rename_template and "{enumeration}" not in rename_template and "{part}" not in rename_template:
                    stem = f"{stem}{enum_str}"
            except Exception:
                stem = f"{date_compact}_{clean_series_title}{enum_str}"
        else:
            stem = f"{date_compact}_{time_zulu}_{clean_series_title}{enum_str}"

        stem = sanitize_filename(stem)
        desired_filename = f"{stem}{ext}"

        # Resolve conflict-free target tracking with reserved_paths
        target_path, sidecar_renames = resolve_unique_rename_target(
            orig_path,
            desired_filename,
            reserved_paths=reserved_paths
        )

        plan.append({
            "index": item_index,
            "original_path": str(orig_path),
            "original_filename": orig_path.name,
            "target_filename": target_path.name,
            "target_path": str(target_path),
            "desired_filename": desired_filename,
            "enum_str": enum_str,
            "part_number": item_index,
            "total_count": total_count,
            "title_with_part": f"{clean_series_title.replace('_', ' ')} (Part {item_index})",
            "sidecars_found": [str(c.name) for c, _ in sidecar_renames],
            "sidecar_renames": [{"from": str(c), "to": str(n)} for c, n in sidecar_renames],
            "recorded_datetime": dt_local.isoformat(),
            "has_conflict": (target_path.name != desired_filename),
            "conflict_detected": (target_path.name != desired_filename)
        })

    return plan

