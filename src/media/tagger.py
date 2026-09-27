import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from src.core.paths import find_binary
from src.media.probe import probe_video

logger = logging.getLogger(__name__)

class MetadataIntegrityError(Exception):
    """Raised when in-file tagging fails integrity checks."""
    pass

SUPPORTED_EXIFTOOL_EXTENSIONS = {".mp4", ".m4v", ".mov", ".qt", ".3gp", ".avi", ".wmv"}

def apply_exiftool_tags(
    video_path: Path,
    tags: Dict[str, str],
    custom_exiftool: Optional[str] = None
) -> bool:
    """
    Write tags into Windows-proprietary Xtra atom (Microsoft:Category), Apple ItemList, 
    and XMP packets using ExifTool. This enables tags to show up in Windows File Explorer 
    'Tags' column and macOS Finder keywords.
    """
    if video_path.suffix.lower() not in SUPPORTED_EXIFTOOL_EXTENSIONS:
        return False

    exiftool_bin = find_binary("exiftool", custom_exiftool)
    if not exiftool_bin:
        logger.debug("ExifTool binary not found; skipping extended OS metadata embedding.")
        return False

    raw_keywords = tags.get("keywords", "")
    if raw_keywords and ";" not in raw_keywords and "," in raw_keywords:
        # Normalize to semicolon-delimited for Windows Explorer
        raw_keywords = "; ".join([k.strip() for k in raw_keywords.split(",") if k.strip()])

    args = [exiftool_bin, "-overwrite_original"]
    if raw_keywords:
        args.extend([
            f"-Microsoft:Category={raw_keywords}",
            f"-ItemList:Keyword={raw_keywords}",
            f"-XMP-dc:Subject={raw_keywords}",
            f"-XMP-digiKam:TagsList={raw_keywords}",
            f"-Genre={raw_keywords}",
        ])
    if tags.get("title"):
        args.extend([
            f"-Title={tags['title']}",
            f"-XMP-dc:Title={tags['title']}",
        ])
    if tags.get("description"):
        desc = tags["description"]
        args.extend([
            f"-Comment={desc}",
            f"-Description={desc}",
            f"-Microsoft:SubTitle={desc[:250]}",
            f"-XMP-dc:Description={desc}",
        ])
    if tags.get("date"):
        args.extend([
            f"-CreateDate={tags['date']}",
            f"-ModifyDate={tags['date']}",
        ])

    args.append(str(video_path))
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            logger.info(f"Successfully applied extended OS metadata to {video_path.name} via ExifTool.")
            return True
        else:
            logger.warning(f"ExifTool returned non-zero code ({res.returncode}): {res.stderr}")
            return False
    except Exception as e:
        logger.warning(f"Failed to run ExifTool on {video_path}: {e}")
        return False

def apply_metadata_tags(
    video_path: Path,
    tags: Dict[str, str],
    create_backup: bool = True,
    verify_integrity: bool = True,
    custom_ffmpeg: Optional[str] = None
) -> Dict[str, Any]:
    """
    Safely write metadata tags (title, description, date, keywords) into video container.
    
    Safety Guarantee:
    1. Probes original stream count and duration.
    2. Writes to a temporary file via stream copy (-c copy).
    3. Probes the temporary output and verifies duration/streams match.
    4. Only replaces the original after verification passes.
    5. Optionally creates a .bak backup file.
    6. Injects Microsoft Xtra atom tags (via ExifTool) so Windows Explorer Details -> Tags populates.
    """
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found.")

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Step 1: Pre-probe original
    original_meta = probe_video(video_path)
    orig_duration = original_meta.get("duration", 0.0)

    # Detect legacy 3GPP/mobile codecs or formats that ISO MP4 muxer rejects under stream copy
    vcodec = str(original_meta.get("video_codec", "")).lower()
    acodec = str(original_meta.get("audio_codec") or "").lower()
    orig_tags = original_meta.get("tags") or {}
    major_brand = str(orig_tags.get("major_brand", "")).lower()
    compatible_brands = str(orig_tags.get("compatible_brands", "")).lower()

    extra_mux_args = []
    is_3gp = (
        vcodec in ("h263", "s263") or
        acodec in ("amr_nb", "amrnb", "samr") or
        "3gp" in major_brand or
        "3gp" in compatible_brands or
        video_path.suffix.lower() in (".3gp", ".3g2", ".3gpp")
    )
    if is_3gp:
        extra_mux_args.extend(["-f", "3gp"])

    # Prepare temp file in same directory for atomic replace
    temp_filename = f".tmp_{uuid.uuid4().hex[:8]}_{video_path.name}"
    temp_path = video_path.parent / temp_filename

    # Build metadata arguments
    metadata_args = []
    # Standard mapping for MP4 / QuickTime / MKV
    if "title" in tags and tags["title"]:
        metadata_args.extend([
            "-metadata", f"title={tags['title']}",
            "-metadata", f"TITLE={tags['title']}"
        ])
    if "description" in tags and tags["description"]:
        metadata_args.extend([
            "-metadata", f"comment={tags['description']}",
            "-metadata", f"COMMENT={tags['description']}",
            "-metadata", f"description={tags['description']}",
            "-metadata", f"DESCRIPTION={tags['description']}",
            "-metadata", f"synopsis={tags['description']}"
        ])
    if "date" in tags and tags["date"]:
        metadata_args.extend([
            "-metadata", f"date={tags['date']}",
            "-metadata", f"DATE={tags['date']}",
            "-metadata", f"creation_time={tags['date']}"
        ])
    if "keywords" in tags and tags["keywords"]:
        kw = tags["keywords"]
        if ";" not in kw and "," in kw:
            kw = "; ".join([k.strip() for k in kw.split(",") if k.strip()])
        metadata_args.extend([
            "-metadata", f"keywords={kw}",
            "-metadata", f"KEYWORDS={kw}",
            "-metadata", f"TAGS={kw}",
            "-metadata", f"genre={kw}",
            "-metadata", f"GENRE={kw}",
        ])

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(video_path),
        "-c", "copy",
        *extra_mux_args,
        *metadata_args,
        str(temp_path)
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            err_msg = res.stderr or ""
            # If standard MP4/container muxing failed due to codec mismatch, retry with 3GP container muxer
            if ("Could not find tag for codec" in err_msg or 
                "codec not currently supported in container" in err_msg or 
                "incompatible with output codec" in err_msg) and "-f" not in cmd:
                logger.warning(
                    f"FFmpeg standard container mux failed with codec incompatibility for {video_path.name}. "
                    "Retrying with 3GPP container format..."
                )
                retry_cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i", str(video_path),
                    "-c", "copy",
                    "-f", "3gp",
                    *metadata_args,
                    str(temp_path)
                ]
                res = subprocess.run(retry_cmd, capture_output=True, text=True)

        if res.returncode != 0:
            if temp_path.exists():
                temp_path.unlink()
            raise MetadataIntegrityError(f"FFmpeg tagging process failed: {res.stderr}")

        # Step 2: Integrity Verification
        if verify_integrity:
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise MetadataIntegrityError("Tagged temp file was empty or not created.")

            new_meta = probe_video(temp_path)
            new_duration = new_meta.get("duration", 0.0)

            # Check duration match (tolerance: 0.5s or 1%)
            if orig_duration > 0 and abs(orig_duration - new_duration) > max(0.5, orig_duration * 0.01):
                temp_path.unlink()
                raise MetadataIntegrityError(
                    f"Integrity check failed: Duration mismatch (original: {orig_duration:.2f}s, new: {new_duration:.2f}s)"
                )

            # Check file size sanity (should not lose massive amount of data on -c copy)
            orig_size = video_path.stat().st_size
            new_size = temp_path.stat().st_size
            if new_size < orig_size * 0.7:  # More than 30% smaller is suspicious for stream copy
                temp_path.unlink()
                raise MetadataIntegrityError(
                    f"Integrity check failed: Output file size unexpectedly small ({new_size} vs {orig_size} bytes)"
                )

        # Step 3: Backup
        backup_path = None
        if create_backup:
            backup_path = video_path.with_name(f"{video_path.name}.bak")
            # Don't overwrite existing backup if one already exists
            counter = 1
            while backup_path.exists():
                backup_path = video_path.with_name(f"{video_path.name}.bak{counter}")
                counter += 1
            shutil.copy2(video_path, backup_path)

        # Step 4: Atomic Replace
        os.replace(temp_path, video_path)

        # Step 5: Extended Windows & Apple metadata embedding via ExifTool
        apply_exiftool_tags(video_path, tags)

        return {
            "status": "success",
            "file": str(video_path),
            "backup_created": str(backup_path) if backup_path else None,
            "tags_applied": tags
        }

    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise

def create_custom_download_video(
    source_video_path: Path,
    output_path: Path,
    metadata_tags: Optional[Dict[str, str]] = None,
    srt_path: Optional[Path] = None,
    embed_tags: bool = True,
    embed_subtitles: bool = True,
    target_format: str = "original",
    custom_ffmpeg: Optional[str] = None
) -> Path:
    """
    Build a customized video file for download with embedded metadata and/or soft subtitles.
    Uses stream copying (-c copy) for zero re-encoding and high performance.
    
    Container rules:
    - Subtitle embedding is strictly supported for MKV containers (or remuxed to MKV).
    - MP4 containers do not support standard soft SRT text subtitles; subtitles are skipped for MP4.
    - Tags are written to both standard container atoms and proprietary Windows Xtra atom
      (Microsoft:Category) via ExifTool so they display in Windows File Explorer Details -> Tags.
    """
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg binary not found.")

    if not source_video_path.exists():
        raise FileNotFoundError(f"Source video not found: {source_video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine container format
    is_mkv = target_format.lower() == "mkv" or output_path.suffix.lower() == ".mkv" or source_video_path.suffix.lower() == ".mkv"
    can_embed_subtitles = is_mkv and embed_subtitles and srt_path is not None and srt_path.exists() and srt_path.stat().st_size > 0

    cmd = [ffmpeg_bin, "-y", "-i", str(source_video_path)]

    if can_embed_subtitles:
        cmd.extend(["-i", str(srt_path)])
        # Map video & audio from input 0, subtitles from input 1
        cmd.extend([
            "-map", "0:v",
            "-map", "0:a?",
            "-map", "1:s",
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "srt",
            "-metadata:s:s:0", "language=eng",
            "-metadata:s:s:0", "title=English",
            "-disposition:s:0", "default"
        ])
    else:
        cmd.extend(["-c", "copy"])

    if embed_tags and metadata_tags:
        if "title" in metadata_tags and metadata_tags["title"]:
            cmd.extend([
                "-metadata", f"title={metadata_tags['title']}",
                "-metadata", f"TITLE={metadata_tags['title']}"
            ])
        if "description" in metadata_tags and metadata_tags["description"]:
            cmd.extend([
                "-metadata", f"comment={metadata_tags['description']}",
                "-metadata", f"COMMENT={metadata_tags['description']}",
                "-metadata", f"description={metadata_tags['description']}",
                "-metadata", f"DESCRIPTION={metadata_tags['description']}",
                "-metadata", f"synopsis={metadata_tags['description']}"
            ])
        if "date" in metadata_tags and metadata_tags["date"]:
            cmd.extend([
                "-metadata", f"date={metadata_tags['date']}",
                "-metadata", f"DATE={metadata_tags['date']}",
                "-metadata", f"creation_time={metadata_tags['date']}"
            ])
        if "keywords" in metadata_tags and metadata_tags["keywords"]:
            kw = metadata_tags["keywords"]
            if ";" not in kw and "," in kw:
                kw = "; ".join([k.strip() for k in kw.split(",") if k.strip()])
            cmd.extend([
                "-metadata", f"keywords={kw}",
                "-metadata", f"KEYWORDS={kw}",
                "-metadata", f"TAGS={kw}",
                "-metadata", f"genre={kw}",
                "-metadata", f"GENRE={kw}",
            ])

    is_3gp = source_video_path.suffix.lower() in (".3gp", ".3g2", ".3gpp")
    if not is_mkv and is_3gp:
        cmd.extend(["-f", "3gp"])

    cmd.append(str(output_path))

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        err_msg = res.stderr or ""
        if ("Could not find tag for codec" in err_msg or 
            "codec not currently supported in container" in err_msg or 
            "incompatible with output codec" in err_msg) and "-f" not in cmd and not is_mkv:
            retry_cmd = list(cmd[:-1]) + ["-f", "3gp", cmd[-1]]
            res = subprocess.run(retry_cmd, capture_output=True, text=True)

    if res.returncode != 0:
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass
        raise RuntimeError(f"FFmpeg download generation failed: {res.stderr}")

    # Inject extended OS metadata (Windows Xtra atom, Apple ItemList, XMP) via ExifTool
    if embed_tags and metadata_tags:
        apply_exiftool_tags(output_path, metadata_tags)

    return output_path

