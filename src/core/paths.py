import os
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "video-describer"

def get_app_root() -> Path:
    """Return the application root directory (where app.py / repo is located)."""
    return Path(__file__).resolve().parent.parent.parent

def is_portable_mode() -> bool:
    """Check if portable mode is enabled."""
    root = get_app_root()
    return (
        os.environ.get("PORTABLE", "").lower() in ("1", "true", "yes")
        or (root / ".portable").exists()
        or (root / "data").is_dir()
    )

def is_docker_mode() -> bool:
    """Check if running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", "") == "1"

def get_base_data_dir() -> Path:
    """Resolve data directory based on environment mode."""
    # 1. Custom explicit environment variable override
    env_dir = os.environ.get("VIDEO_DESCRIBER_DATA_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Docker container environment
    if is_docker_mode():
        docker_p = Path("/data")
        docker_p.mkdir(parents=True, exist_ok=True)
        return docker_p

    # 3. Portable mode
    if is_portable_mode():
        portable_p = get_app_root() / "data"
        portable_p.mkdir(parents=True, exist_ok=True)
        return portable_p

    # 4. Standard OS paths
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux / BSD
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    data_dir = base / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def get_cache_dir() -> Path:
    """Resolve cache directory for extracted frames, temporary audio, etc."""
    if is_portable_mode():
        c = get_base_data_dir() / "cache"
    elif is_docker_mode():
        c = get_base_data_dir() / "cache"
    elif sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        c = local / APP_NAME / "cache"
    elif sys.platform == "darwin":
        c = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        c = xdg_cache / APP_NAME

    c.mkdir(parents=True, exist_ok=True)
    return c

def get_config_path() -> Path:
    """Return path to config.json."""
    return get_base_data_dir() / "config.json"

def get_history_path() -> Path:
    """Return path to batch and rename history directory."""
    h = get_base_data_dir() / "history"
    h.mkdir(parents=True, exist_ok=True)
    return h

def get_models_dir() -> Path:
    """Return path for downloaded AI models (e.g. Whisper weights)."""
    m = get_base_data_dir() / "models" / "whisper"
    m.mkdir(parents=True, exist_ok=True)
    return m

def get_uploads_dir() -> Path:
    """Return staging directory for drag-and-drop uploaded videos."""
    u = get_base_data_dir() / "uploads"
    u.mkdir(parents=True, exist_ok=True)
    return u

def get_faces_dir() -> Path:
    """Return directory for face recognition database and thumbnail crops."""
    f = get_base_data_dir() / "faces"
    f.mkdir(parents=True, exist_ok=True)
    (f / "thumbs").mkdir(parents=True, exist_ok=True)
    return f

def get_logs_dir() -> Path:
    """Return directory for persistent application logs."""
    logs_dir = get_base_data_dir() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir

def find_binary(binary_name: str, custom_path: Optional[str] = None) -> Optional[str]:
    """Find a binary (e.g. ffmpeg or ffprobe) checking custom path, bundled bin/, data bin/, and PATH."""
    import shutil

    if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
        return custom_path

    exe_suffix = ".exe" if sys.platform.startswith("win") else ""

    # Check local application bin/ directory (e.g. for portable distributions)
    local_bin = get_app_root() / "bin" / (binary_name + exe_suffix)
    if local_bin.is_file() and os.access(local_bin, os.X_OK):
        return str(local_bin)

    # Check data directory bin/
    data_bin = get_base_data_dir() / "bin" / (binary_name + exe_suffix)
    if data_bin.is_file() and os.access(data_bin, os.X_OK):
        return str(data_bin)

    # Check system PATH
    found = shutil.which(binary_name)
    if found:
        return found

    # If looking for ffmpeg and not found yet, check imageio-ffmpeg package
    if binary_name == "ffmpeg":
        try:
            import imageio_ffmpeg # type: ignore
            img_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if img_exe and os.path.isfile(img_exe) and os.access(img_exe, os.X_OK):
                return img_exe
        except Exception:
            pass

    return None

