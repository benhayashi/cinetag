import os
import shutil
from pathlib import Path
from typing import Dict, Any

from src.core.paths import (
    get_cache_dir,
    get_history_path,
    get_base_data_dir,
    get_config_path,
    get_models_dir,
    get_uploads_dir
)

def get_directory_size(path: Path) -> int:
    """Calculate total size of directory in bytes."""
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total

def get_storage_stats() -> Dict[str, Any]:
    """Return overview of all application storage locations and sizes."""
    cache_dir = get_cache_dir()
    history_dir = get_history_path()
    base_dir = get_base_data_dir()
    config_file = get_config_path()
    models_dir = get_models_dir()
    uploads_dir = get_uploads_dir()

    cache_size = get_directory_size(cache_dir)
    history_size = get_directory_size(history_dir)
    models_size = get_directory_size(models_dir)
    uploads_size = get_directory_size(uploads_dir)
    config_size = config_file.stat().st_size if config_file.exists() else 0

    # Count items
    frame_count = len(list(cache_dir.glob("**/*.jpg"))) + len(list(cache_dir.glob("**/*.png")))
    audio_count = len(list(cache_dir.glob("**/*.wav"))) + len(list(cache_dir.glob("**/*.mp3")))
    upload_count = len([p for p in uploads_dir.iterdir() if p.is_file()])

    return {
        "locations": {
            "base_data_dir": str(base_dir),
            "cache_dir": str(cache_dir),
            "history_dir": str(history_dir),
            "models_dir": str(models_dir),
            "uploads_dir": str(uploads_dir),
            "config_file": str(config_file),
        },
        "sizes_bytes": {
            "cache": cache_size,
            "history": history_size,
            "models": models_size,
            "uploads": uploads_size,
            "config": config_size,
            "total": cache_size + history_size + models_size + uploads_size + config_size
        },
        "counts": {
            "frames": frame_count,
            "audio_files": audio_count,
            "uploads": upload_count
        }
    }

def clear_uploads() -> int:
    """Purge all files in the uploads staging directory. Returns freed bytes."""
    uploads_dir = get_uploads_dir()
    freed = get_directory_size(uploads_dir)
    if uploads_dir.exists():
        shutil.rmtree(uploads_dir, ignore_errors=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return freed


def clear_cache() -> int:
    """Purge all extracted video frames and temporary audio files. Returns freed bytes."""
    cache_dir = get_cache_dir()
    freed = get_directory_size(cache_dir)
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return freed

def clear_history() -> int:
    """Purge batch logs and rename transaction histories. Returns freed bytes."""
    history_dir = get_history_path()
    freed = get_directory_size(history_dir)
    if history_dir.exists():
        shutil.rmtree(history_dir, ignore_errors=True)
    history_dir.mkdir(parents=True, exist_ok=True)
    return freed

def cleanup_video_cache(video_path: Path) -> int:
    """
    Remove temporary frame directory and audio WAV for a specific video.
    Returns total freed bytes.
    """
    cache_dir = get_cache_dir()
    video_hash = f"{video_path.stem}_{int(video_path.stat().st_mtime)}"
    freed = 0

    # Delete frame folder
    frame_dir = cache_dir / "frames" / video_hash
    if frame_dir.exists():
        freed += get_directory_size(frame_dir)
        shutil.rmtree(frame_dir, ignore_errors=True)

    # Delete audio file
    audio_file = cache_dir / "audio" / f"{video_hash}.wav"
    if audio_file.exists():
        freed += audio_file.stat().st_size
        try:
            audio_file.unlink()
        except Exception:
            pass

    return freed

def purge_expired_cache(policy: str) -> int:
    """
    Purge cache items according to the retention policy window.
    policy: 'immediate' | '1_day' | '7_days' | '30_days' | 'persistent'
    Returns freed bytes.
    """
    import time
    if policy == "persistent":
        return 0
    if policy == "immediate":
        return clear_cache()

    day_map = {
        "1_day": 1,
        "7_days": 7,
        "30_days": 30
    }
    days = day_map.get(policy)
    if not days:
        return 0

    cutoff = time.time() - (days * 86400)
    freed = 0
    cache_dir = get_cache_dir()

    # 1. Prune audio WAV files older than cutoff
    audio_dir = cache_dir / "audio"
    if audio_dir.exists():
        for f in audio_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                sz = f.stat().st_size
                try:
                    f.unlink()
                    freed += sz
                except Exception:
                    pass

    # 2. Prune extracted frame directories older than cutoff
    frames_dir = cache_dir / "frames"
    if frames_dir.exists():
        for d in frames_dir.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                sz = get_directory_size(d)
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    freed += sz
                except Exception:
                    pass

    return freed

def factory_reset() -> Dict[str, int]:
    """Completely wipe application cache, history, and config."""
    cache_freed = clear_cache()
    history_freed = clear_history()
    config_file = get_config_path()
    if config_file.exists():
        config_file.unlink()
    return {
        "cache_freed_bytes": cache_freed,
        "history_freed_bytes": history_freed
    }
