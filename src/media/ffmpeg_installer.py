import io
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional

from src.core.paths import get_app_root, find_binary

logger = logging.getLogger(__name__)

# Static release URLs for standalone binaries
URLS = {
    "Linux": {
        "x86_64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "aarch64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
    },
    "Windows": {
        "AMD64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    },
    "Darwin": {
        "x86_64": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "arm64": "https://evermeet.cx/ffmpeg/getrelease/zip"
    }
}

def get_binary_info(binary_path: Optional[str]) -> Dict[str, Any]:
    """Test a binary path and return its version or error."""
    if not binary_path or not os.path.isfile(binary_path):
        return {"available": False, "path": None, "version": None}

    try:
        res = subprocess.run(
            [binary_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            first_line = res.stdout.splitlines()[0] if res.stdout else "Available"
            return {
                "available": True,
                "path": str(Path(binary_path).resolve()),
                "version": first_line
            }
    except Exception as e:
        logger.warning(f"Error running binary {binary_path}: {e}")

    return {"available": False, "path": binary_path, "version": None}

def check_ffmpeg_status(custom_ffmpeg: Optional[str] = None, custom_ffprobe: Optional[str] = None) -> Dict[str, Any]:
    """Check availability and version of ffmpeg and ffprobe."""
    ffmpeg_bin = find_binary("ffmpeg", custom_ffmpeg)
    ffprobe_bin = find_binary("ffprobe", custom_ffprobe)

    ffmpeg_info = get_binary_info(ffmpeg_bin)
    ffprobe_info = get_binary_info(ffprobe_bin)

    return {
        "all_ready": ffmpeg_info["available"] and ffprobe_info["available"],
        "ffmpeg": ffmpeg_info,
        "ffprobe": ffprobe_info
    }

def install_standalone_ffmpeg() -> Dict[str, Any]:
    """
    Download and install standalone static FFmpeg and FFprobe binaries into the application's bin/ folder.
    Works on Linux and Windows without requiring admin/sudo privileges.
    """
    bin_dir = get_app_root() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    os_type = platform.system()
    arch = platform.machine()

    logger.info(f"Initiating FFmpeg standalone installation for {os_type} ({arch})...")

    # Method 1: Check if imageio_ffmpeg is already available to get ffmpeg
    try:
        import imageio_ffmpeg
        img_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if img_exe and os.path.exists(img_exe):
            target_ffmpeg = bin_dir / ("ffmpeg.exe" if os_type == "Windows" else "ffmpeg")
            if not target_ffmpeg.exists():
                shutil.copy2(img_exe, target_ffmpeg)
                target_ffmpeg.chmod(target_ffmpeg.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                logger.info(f"Copied imageio-ffmpeg binary to {target_ffmpeg}")
    except Exception as e:
        logger.debug(f"imageio-ffmpeg extraction skipped: {e}")

    # Method 2: Download static build to get both ffmpeg and ffprobe
    url_map = URLS.get(os_type, {})
    download_url = url_map.get(arch) or url_map.get("x86_64") or url_map.get("AMD64")

    if not download_url:
        # If no specific static URL for this arch, verify if we at least have ffmpeg from imageio
        status = check_ffmpeg_status()
        if status["ffmpeg"]["available"]:
            return {
                "status": "partial",
                "message": "FFmpeg is installed. Please install ffprobe via your system package manager.",
                **status
            }
        raise RuntimeError(f"Automated download not available for OS={os_type}, Arch={arch}. Please install FFmpeg manually.")

    logger.info(f"Downloading static package from {download_url}...")
    headers = {"User-Agent": "HomeVideoAI-Installer"}
    req = urllib.request.Request(download_url, headers=headers)

    with urllib.request.urlopen(req, timeout=120) as resp:
        content = resp.read()

    logger.info(f"Downloaded {len(content)} bytes. Extracting to {bin_dir}...")

    # Extract based on file type
    if download_url.endswith(".tar.xz"):
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:xz") as tar:
            for member in tar.getmembers():
                base_name = Path(member.name).name
                if base_name in ("ffmpeg", "ffprobe"):
                    member_file = tar.extractfile(member)
                    if member_file:
                        dest = bin_dir / base_name
                        with open(dest, "wb") as f_out:
                            f_out.write(member_file.read())
                        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                        logger.info(f"Extracted {base_name} -> {dest}")

    elif download_url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for zip_info in zf.infolist():
                base_name = Path(zip_info.filename).name
                if base_name in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
                    dest = bin_dir / base_name
                    with zf.open(zip_info) as src, open(dest, "wb") as f_out:
                        f_out.write(src.read())
                    if not base_name.endswith(".exe"):
                        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                    logger.info(f"Extracted {base_name} -> {dest}")

    # Re-check status
    final_status = check_ffmpeg_status()
    if not final_status["ffmpeg"]["available"]:
        raise RuntimeError("FFmpeg extraction finished but binary could not be verified.")

    return {
        "status": "success",
        "message": "FFmpeg and FFprobe installed successfully!",
        **final_status
    }
