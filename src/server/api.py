import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import shutil
import sys
import subprocess
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, File, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from src.core.paths import get_uploads_dir, get_faces_dir, get_cache_dir, get_logs_dir
from src.core.config import AppConfig, load_config, save_config
from src.core.privacy import (
    get_storage_stats,
    clear_cache,
    clear_history,
    clear_uploads,
    factory_reset
)
from src.media.probe import SUPPORTED_EXTENSIONS, is_video_file, probe_video
from src.media.renamer import generate_suggested_name, execute_rename, undo_last_rename
from src.media.tagger import apply_metadata_tags
from src.media.ffmpeg_installer import check_ffmpeg_status, install_standalone_ffmpeg, get_binary_info
from src.media.faces import face_registry
from src.ai.ollama_provider import OllamaVisionProvider
from src.ai.openai_provider import OpenAICompatibleVisionProvider
from src.ai.whisper_service import WhisperTranscriptionService
from src.server.queue_manager import manager


router = APIRouter(prefix="/api")

class VerifyBinaryRequest(BaseModel):
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None


# --- Scanning Models ---
class ScanRequest(BaseModel):
    folder_path: str
    recursive: bool = False
    hide_processed: bool = False

class DroppedFileMeta(BaseModel):
    name: str
    size: Optional[int] = None

class ResolveLocalFilesRequest(BaseModel):
    uris: Optional[List[str]] = []
    filenames: Optional[List[str]] = []
    files_meta: Optional[List[DroppedFileMeta]] = []
    current_folder: Optional[str] = None

class AddQueueRequest(BaseModel):
    file_paths: List[str]
    conflict_mode: str = "overwrite"  # "overwrite" | "enumerate"
    date_override: Optional[str] = None
    date_source: Optional[str] = None

class CheckConflictsRequest(BaseModel):
    file_paths: List[str]

class RenamePreviewRequest(BaseModel):
    file_paths: List[str]
    date_override: Optional[str] = None
    date_source: Optional[str] = "smart"  # "smart" | "filename" | "metadata" | "override"
    template: Optional[str] = None
    max_title_length: Optional[int] = None
    include_names: Optional[bool] = None

class RenameExecuteRequest(BaseModel):
    original_path: str
    new_filename: str
    new_creation_date: Optional[str] = None


class TagRequest(BaseModel):
    video_path: str
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    keywords: Optional[str] = None
    create_backup: bool = True
    verify_integrity: bool = True

class RenamePersonRequest(BaseModel):
    new_name: str
    update_sidecars: bool = True

class MergePersonsRequest(BaseModel):
    source_id: str
    target_id: str

class TestCompreFaceRequest(BaseModel):
    url: str
    api_key: str

def format_size(size_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

# --- Endpoints ---

@router.get("/status")
def get_queue_status():
    return manager.get_status()

@router.get("/logs/download")
def download_application_logs():
    """Download persistent application log file."""
    log_file = get_logs_dir() / "video_describer.log"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_filename = f"video_describer_logs_{timestamp}.log"
    
    chunks = []
    # If rotated files exist (.log.1, etc.), include them for historical context
    for rot in sorted(get_logs_dir().glob("video_describer.log.*"), reverse=True):
        try:
            chunks.append(f"=== ROTATED LOG CHUNK ({rot.name}) ===\n" + rot.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
            
    if log_file.exists():
        try:
            chunks.append(log_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
            
    if not chunks and manager.logs:
        chunks = ["\n".join(f"{entry.get('timestamp','')} [{entry.get('level', 'info').upper()}] {entry.get('message','')}" for entry in manager.logs)]
        
    full_log_text = "\n\n".join(chunks) if chunks else "No logs recorded yet.\n"
    
    return Response(
        content=full_log_text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"'
        }
    )

# --- FFmpeg & Binary Detection / Installation ---

@router.get("/ffmpeg/status")
def get_ffmpeg_status():
    cfg = load_config()
    return check_ffmpeg_status(cfg.ffmpeg_path, cfg.ffprobe_path)

@router.post("/ffmpeg/verify")
def verify_binary_paths(req: VerifyBinaryRequest):
    """Test user-provided custom binary paths."""
    ffmpeg_res = get_binary_info(req.ffmpeg_path) if req.ffmpeg_path else {"available": False}
    ffprobe_res = get_binary_info(req.ffprobe_path) if req.ffprobe_path else {"available": False}
    return {
        "ffmpeg": ffmpeg_res,
        "ffprobe": ffprobe_res
    }

@router.post("/ffmpeg/install")
def install_ffmpeg_binary():
    """In-app 1-click download and installation of standalone FFmpeg and FFprobe into ./bin/."""
    try:
        res = install_standalone_ffmpeg()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/add")
def add_to_queue(req: AddQueueRequest):
    added = manager.add_to_queue(
        req.file_paths,
        conflict_mode=req.conflict_mode,
        date_override=req.date_override,
        date_source=req.date_source
    )
    return {"status": "ok", "added_count": len(added)}

def find_existing_sidecars(p: Path) -> List[str]:
    parent = p.parent
    stem = p.stem
    name = p.name
    found = []
    if any(f.exists() for f in [parent / f"{stem}.info.json", parent / f"{name}.info.json"]):
        found.append(".info.json")
    if any(f.exists() for f in [parent / f"{name}.txt", parent / f"{stem}.txt"]):
        found.append(".txt")
    if any(f.exists() for f in [parent / f"{stem}.nfo", parent / f"{name}.nfo"]):
        found.append(".nfo")
    if any(f.exists() for f in [parent / f"{stem}.xmp", parent / f"{name}.xmp"]):
        found.append(".xmp")
    if any(f.exists() for f in [parent / f"{name}.edl", parent / f"{stem}.edl"]):
        found.append(".edl")
    return found

@router.post("/queue/check-conflicts")
def check_queue_conflicts(req: CheckConflictsRequest):
    conflicts = []
    for fp in req.file_paths:
        p = Path(fp)
        if not p.exists():
            continue
        sc = find_existing_sidecars(p)
        if sc:
            conflicts.append({
                "path": str(p.resolve()),
                "filename": p.name,
                "sidecars": sc
            })
    return {"has_conflicts": len(conflicts) > 0, "conflicts": conflicts}

@router.post("/queue/start")
def start_queue():
    manager.start()
    return {"status": "ok"}

@router.post("/queue/pause")
def pause_queue():
    manager.pause()
    return {"status": "ok"}

@router.post("/queue/clear")
def clear_queue():
    manager.clear()
    return {"status": "ok"}

@router.post("/queue/clear-completed")
def clear_completed_queue():
    removed = manager.clear_completed()
    return {"status": "ok", "cleared_count": removed}

@router.get("/fs/browse")
def browse_filesystem(path: Optional[str] = None):
    """
    Browse directories and video files on the host filesystem.
    Enables interactive web-based folder and file selection dialogs across any OS or network LAN.
    """
    if path and path.strip():
        target = Path(path.strip()).resolve()
    else:
        target = Path.home().resolve()

    if not target.exists() or not target.is_dir():
        target = Path.home().resolve()

    quick_locations = []
    home = Path.home().resolve()
    quick_locations.append({"name": "🏠 Home", "path": str(home)})

    for name, icon in [("Videos", "🎥"), ("Movies", "🎬"), ("Documents", "📄"), ("Downloads", "📥"), ("Desktop", "🖥️")]:
        cand = home / name
        if cand.exists() and cand.is_dir():
            quick_locations.append({"name": f"{icon} {name}", "path": str(cand.resolve())})

    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                quick_locations.append({"name": f"💾 Drive ({letter}:)", "path": str(drive)})
    else:
        quick_locations.append({"name": "💾 Root (/)", "path": "/"})
        media_mnt = Path("/media")
        if media_mnt.exists() and media_mnt.is_dir():
            quick_locations.append({"name": "📁 /media", "path": str(media_mnt)})
        mnt = Path("/mnt")
        if mnt.exists() and mnt.is_dir():
            quick_locations.append({"name": "📁 /mnt", "path": str(mnt)})

    folders = []
    files = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: x.name.lower()):
            if entry.name.startswith("."):
                continue  # skip hidden files
            try:
                if entry.is_dir():
                    folders.append({
                        "name": entry.name,
                        "path": str(entry.resolve())
                    })
                elif entry.is_file() and is_video_file(entry):
                    stat = entry.stat()
                    files.append({
                        "name": entry.name,
                        "path": str(entry.resolve()),
                        "size": stat.st_size,
                        "size_formatted": format_size(stat.st_size)
                    })
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {e}")

    parent = str(target.parent.resolve()) if target.parent != target else None

    return {
        "current_path": str(target),
        "parent_path": parent,
        "quick_locations": quick_locations,
        "folders": folders,
        "files": files
    }

class NativePickRequest(BaseModel):
    target: str = "folder"  # "folder" | "files"
    initial_dir: Optional[str] = None

def pick_native_directory(initial_dir: Optional[str] = None) -> Dict[str, Any]:
    """Open native OS directory selection window."""
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    
    # 1. Linux Zenity
    if sys.platform.startswith("linux") and shutil.which("zenity") and has_display:
        cmd = ["zenity", "--file-selection", "--directory", "--title=Select Video Folder"]
        if initial_dir and Path(initial_dir).is_dir():
            cmd.append(f"--filename={Path(initial_dir).resolve()}/")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                return {"status": "selected", "path": res.stdout.strip()}
            elif res.returncode == 1:
                return {"status": "cancelled"}
        except Exception as e:
            logger.warning(f"Zenity folder dialog error: {e}")

    # 2. macOS AppleScript
    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "Select Video Folder")'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                return {"status": "selected", "path": res.stdout.strip()}
            else:
                return {"status": "cancelled"}
        except Exception:
            return {"status": "cancelled"}

    # 3. Windows PowerShell
    if os.name == "nt":
        ps_cmd = "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = 'Select Video Folder'; if ($f.ShowDialog() -eq 'OK') { Write-Host -NoNewline $f.SelectedPath }"
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                return {"status": "selected", "path": res.stdout.strip()}
            else:
                return {"status": "cancelled"}
        except Exception:
            pass

    # 4. Tkinter fallback
    if has_display or os.name == "nt":
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(initialdir=initial_dir or str(Path.home()), title="Select Video Folder")
            root.destroy()
            if selected and Path(selected).is_dir():
                return {"status": "selected", "path": str(Path(selected).resolve())}
            return {"status": "cancelled"}
        except Exception as e:
            logger.warning(f"Tkinter folder dialog error: {e}")

    return {"status": "unsupported"}

def pick_native_files(initial_dir: Optional[str] = None) -> Dict[str, Any]:
    """Open native OS file selection window."""
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    # 1. Linux Zenity
    if sys.platform.startswith("linux") and shutil.which("zenity") and has_display:
        cmd = [
            "zenity", "--file-selection", "--multiple", "--separator=|",
            "--title=Select Video Clips",
            "--file-filter=Video files | *.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mts *.MP4 *.MOV *.MKV *.AVI *.WEBM *.MTS"
        ]
        if initial_dir and Path(initial_dir).is_dir():
            cmd.append(f"--filename={Path(initial_dir).resolve()}/")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                paths = [p.strip() for p in res.stdout.strip().split("|") if p.strip()]
                return {"status": "selected", "paths": paths}
            elif res.returncode == 1:
                return {"status": "cancelled"}
        except Exception as e:
            logger.warning(f"Zenity files dialog error: {e}")

    # 2. macOS AppleScript
    if sys.platform == "darwin":
        script = 'set chosen to choose file with prompt "Select Video Clips" of type {"public.movie", "mp4", "mov", "mkv", "avi"} with multiple selections allowed\nset out to ""\nrepeat with f in chosen\nset out to out & POSIX path of f & linefeed\nend repeat\nout'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                paths = [p.strip() for p in res.stdout.strip().splitlines() if p.strip()]
                return {"status": "selected", "paths": paths}
            else:
                return {"status": "cancelled"}
        except Exception:
            return {"status": "cancelled"}

    # 3. Windows PowerShell
    if os.name == "nt":
        ps_cmd = "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null; $f = New-Object System.Windows.Forms.OpenFileDialog; $f.Multiselect = $true; $f.Filter = 'Video files (*.mp4;*.mov;*.mkv;*.avi)|*.mp4;*.mov;*.mkv;*.avi|All files (*.*)|*.*'; if ($f.ShowDialog() -eq 'OK') { [string]::Join('|', $f.FileNames) }"
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=180)
            if res.returncode == 0 and res.stdout.strip():
                paths = [p.strip() for p in res.stdout.strip().split("|") if p.strip()]
                return {"status": "selected", "paths": paths}
            else:
                return {"status": "cancelled"}
        except Exception:
            pass

    # 4. Tkinter fallback
    if has_display or os.name == "nt":
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            files = filedialog.askopenfilenames(
                initialdir=initial_dir or str(Path.home()),
                title="Select Video Clips",
                filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mts"), ("All files", "*.*")]
            )
            root.destroy()
            if files:
                return {"status": "selected", "paths": [str(Path(f).resolve()) for f in files]}
            return {"status": "cancelled"}
        except Exception as e:
            logger.warning(f"Tkinter files dialog error: {e}")

    return {"status": "unsupported"}

@router.post("/fs/pick-native")
def pick_native_dialog(req: NativePickRequest):
    """
    Open native desktop file/folder dialog window on the host OS.
    Returns status: 'selected' with path(s), 'cancelled', or 'unsupported'.
    """
    if req.target == "folder":
        res = pick_native_directory(req.initial_dir)
        if isinstance(res, dict):
            return res
        elif res:
            return {"status": "selected", "path": str(res)}
        return {"status": "cancelled"}
    else:
        res = pick_native_files(req.initial_dir)
        if isinstance(res, dict):
            return res
        elif res:
            return {"status": "selected", "paths": list(res)}
        return {"status": "cancelled"}

@router.post("/scan")
def scan_directory(req: ScanRequest):
    folder = Path(req.folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail="Invalid folder path")

    videos = []
    pattern = "**/*" if req.recursive else "*"

    for p in folder.glob(pattern):
        if is_video_file(p):
            # Check for existing sidecar
            has_txt = (p.parent / f"{p.name}.txt").exists() or (p.parent / f"{p.stem}.txt").exists()
            has_json = (p.parent / f"{p.stem}.info.json").exists()
            is_processed = has_txt or has_json

            # Accompanying .srt check
            from src.media.subtitles import find_accompanying_srt
            acc_srt = find_accompanying_srt(p)

            if req.hide_processed and is_processed:
                continue

            try:
                stat = p.stat()
                videos.append({
                    "path": str(p.resolve()),
                    "filename": p.name,
                    "parent_dir": str(p.parent),
                    "size_bytes": stat.st_size,
                    "size_formatted": format_size(stat.st_size),
                    "has_sidecar": is_processed,
                    "has_srt": acc_srt is not None,
                    "srt_filename": acc_srt.name if acc_srt else None
                })
            except Exception:
                pass

    return {
        "folder": str(folder.resolve()),
        "total_found": len(videos),
        "files": videos
    }

@router.post("/files/resolve-local")
def resolve_local_files(req: ResolveLocalFilesRequest):
    """
    Resolve local files and directories dropped via Mode A for in-place processing.
    Parses file:/// URIs, searches recently-used activity logs, and performs recursive
    candidate directory traversal without copying/uploading files.
    """
    import urllib.parse
    resolved = []
    seen = set()

    def add_path(p: Path):
        try:
            rp = p.resolve()
            if str(rp) not in seen and is_video_file(rp):
                seen.add(str(rp))
                resolved.append(str(rp))
        except Exception:
            pass

    def scan_path(p: Path):
        try:
            rp = p.resolve()
            if rp.is_file() and is_video_file(rp):
                add_path(rp)
            elif rp.is_dir():
                for sub in rp.rglob("*"):
                    if is_video_file(sub):
                        add_path(sub)
        except Exception:
            pass

    # 1. Process explicit URIs or file paths
    for item in (req.uris or []):
        if not item or not item.strip():
            continue
        raw = item.strip()
        if raw.startswith("file://"):
            parsed = urllib.parse.urlparse(raw)
            path_str = urllib.parse.unquote(parsed.path)
            if len(path_str) >= 3 and path_str[0] == '/' and path_str[2] == ':':
                path_str = path_str[1:]
            p = Path(path_str)
        else:
            p = Path(raw)

        if p.exists():
            scan_path(p)

    # 2. Extract recent files from Linux ~/.local/share/recently-used.xbel
    recent_videos_map: Dict[str, List[Path]] = {}
    xbel_file = Path.home() / ".local" / "share" / "recently-used.xbel"
    if xbel_file.exists():
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(str(xbel_file))
            for bm in tree.getroot().findall(".//bookmark"):
                href = bm.get("href")
                if href and href.startswith("file://"):
                    raw_p = urllib.parse.unquote(urllib.parse.urlparse(href).path)
                    cand_p = Path(raw_p)
                    if cand_p.exists() and is_video_file(cand_p):
                        recent_videos_map.setdefault(cand_p.name, []).append(cand_p)
        except Exception as e:
            logger.debug(f"Failed parsing recently-used.xbel: {e}")

    # Build target filenames with optional size
    targets: List[Tuple[str, Optional[int]]] = []
    if req.files_meta:
        for fm in req.files_meta:
            if fm.name and fm.name.strip():
                targets.append((fm.name.strip(), fm.size))
    for fn in (req.filenames or []):
        if fn and fn.strip() and not any(t[0] == fn.strip() for t in targets):
            targets.append((fn.strip(), None))

    # Candidate search roots
    candidate_dirs: List[Path] = []
    if req.current_folder and req.current_folder.strip():
        cf = Path(req.current_folder.strip())
        if cf.exists() and cf.is_dir():
            candidate_dirs.append(cf)

    home = Path.home()
    for std in ["Desktop", "Videos", "Downloads", "Movies", "Documents"]:
        sp = home / std
        if sp.exists() and sp.is_dir():
            if sp not in candidate_dirs:
                candidate_dirs.append(sp)
            try:
                for sub in sp.iterdir():
                    if sub.is_dir() and sub not in candidate_dirs:
                        candidate_dirs.append(sub)
            except Exception:
                pass

    # Removable media mounts
    for mnt_base in ["/media", "/mnt"]:
        mb = Path(mnt_base)
        if mb.exists() and mb.is_dir() and mb not in candidate_dirs:
            candidate_dirs.append(mb)

    if home not in candidate_dirs:
        candidate_dirs.append(home)

    for fn, expected_size in targets:
        # Check if already resolved as file or in resolved paths
        if any(Path(r).name == fn for r in resolved):
            continue

        # A. Check if raw string is an existing absolute path
        p_direct = Path(fn)
        if p_direct.is_absolute() and p_direct.exists():
            scan_path(p_direct)
            continue

        # B. Check recently-used.xbel map
        if fn in recent_videos_map:
            matched_recent = False
            for cand_p in recent_videos_map[fn]:
                if expected_size is None or cand_p.stat().st_size == expected_size:
                    add_path(cand_p)
                    if cand_p.parent not in candidate_dirs:
                        candidate_dirs.insert(0, cand_p.parent)
                    matched_recent = True
                    break
            if matched_recent:
                continue

        # C. Check direct child of candidate dirs (file OR folder, exact or case-insensitive)
        found = False
        fn_lower = fn.lower()
        for cd in candidate_dirs:
            cand = cd / fn
            if cand.exists():
                if cand.is_file() and is_video_file(cand):
                    if expected_size is None or cand.stat().st_size == expected_size:
                        add_path(cand)
                        found = True
                        break
                elif cand.is_dir():
                    scan_path(cand)
                    found = True
                    break

            if not found and cd.exists():
                try:
                    for child in cd.iterdir():
                        if child.name.lower() == fn_lower:
                            if child.is_file() and is_video_file(child):
                                if expected_size is None or child.stat().st_size == expected_size:
                                    add_path(child)
                                    found = True
                                    break
                            elif child.is_dir():
                                scan_path(child)
                                found = True
                                break
                    if found:
                        break
                except Exception:
                    pass

        # D. Deep search in candidate directories (depth up to 4)
        if not found:
            for cd in list(candidate_dirs):
                if not cd.exists() or not cd.is_dir():
                    continue
                try:
                    for root, dirs, files in os.walk(cd):
                        rel = Path(root).relative_to(cd)
                        if len(rel.parts) > 4:
                            dirs.clear()
                            continue
                        for f in files:
                            if f == fn or f.lower() == fn_lower:
                                cand = Path(root) / f
                                if is_video_file(cand) and (expected_size is None or cand.stat().st_size == expected_size):
                                    add_path(cand)
                                    if cand.parent not in candidate_dirs:
                                        candidate_dirs.insert(0, cand.parent)
                                    found = True
                                    break
                        if found:
                            break
                        for d in dirs:
                            if d == fn or d.lower() == fn_lower:
                                cand = Path(root) / d
                                scan_path(cand)
                                found = True
                                break
                        if found:
                            break
                    if found:
                        break
                except Exception:
                    pass

    detected_folder = None
    if resolved:
        detected_folder = str(Path(resolved[0]).parent)

    return {
        "status": "ok",
        "resolved_paths": resolved,
        "count": len(resolved),
        "detected_folder": detected_folder
    }

@router.get("/config")
def get_config():
    return load_config().model_dump()

@router.post("/config")
def update_config(config_data: Dict[str, Any]):
    current = load_config()
    updated = current.model_copy(update=config_data)
    save_config(updated)
    return {"status": "ok", "config": updated.model_dump()}

@router.get("/config/export")
def export_config():
    """Export the current system configuration as a machine-readable JSON file."""
    cfg = load_config()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_payload = {
        "app": "home-video-ai",
        "version": "2.3.0",
        "exported_at": datetime.now().isoformat(),
        "config": cfg.model_dump()
    }
    content = json.dumps(export_payload, indent=2)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="video_describer_config_{timestamp}.json"'
        }
    )

@router.post("/config/import")
async def import_config(
    file: Optional[UploadFile] = File(None),
    config_data: Optional[Dict[str, Any]] = None
):
    """
    Import and apply a configuration setup from an uploaded JSON file or JSON payload.
    """
    imported_dict = None
    if file:
        try:
            content = await file.read()
            data = json.loads(content.decode("utf-8"))
            if isinstance(data, dict):
                imported_dict = data.get("config", data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON configuration file: {e}")
    elif config_data:
        imported_dict = config_data.get("config", config_data)
    else:
        raise HTTPException(status_code=400, detail="No configuration file or JSON payload provided")

    if not isinstance(imported_dict, dict):
        raise HTTPException(status_code=400, detail="Configuration data must be a JSON object")

    try:
        current = load_config()
        updated = current.model_copy(update=imported_dict)
        save_config(updated)
        return {
            "status": "ok",
            "message": "Settings imported successfully",
            "config": updated.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to apply configuration: {e}")

@router.get("/models/ollama")
def list_ollama_models():
    cfg = load_config()
    provider = OllamaVisionProvider(base_url=cfg.ollama_url)
    available = provider.is_available()
    models = provider.list_models() if available else []
    return {
        "connected": available,
        "url": cfg.ollama_url,
        "models": models
    }

@router.get("/models/openai")
def list_openai_models():
    cfg = load_config()
    provider = OpenAICompatibleVisionProvider(
        base_url=cfg.openai_compatible_url,
        api_key=cfg.openai_compatible_api_key
    )
    available = provider.is_available()
    models = provider.list_models() if available else []
    return {
        "connected": available,
        "url": cfg.openai_compatible_url,
        "models": models
    }

class WhisperRemoteProbeRequest(BaseModel):
    url: str
    api_key: Optional[str] = ""
    model: Optional[str] = "base"

@router.get("/models/whisper")
def check_whisper():
    cfg = load_config()
    svc = WhisperTranscriptionService(
        backend=cfg.whisper_backend,
        model_name=cfg.whisper_model,
        remote_url=cfg.whisper_remote_url,
        api_key=getattr(cfg, "whisper_api_key", None)
    )
    return svc.is_available()

@router.post("/whisper/test-remote")
def probe_whisper_remote(req: WhisperRemoteProbeRequest):
    """Test connection to an OpenAI-compatible remote Whisper server."""
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Server address / URL is required")

    import httpx
    import time
    from src.ai.whisper_service import normalize_whisper_urls

    transcribe_url, base_url = normalize_whisper_urls(req.url.strip())
    headers = {}
    if req.api_key and req.api_key.strip():
        headers["Authorization"] = f"Bearer {req.api_key.strip()}"

    discovered_models = []
    t0 = time.time()
    errors = []
    models_found = False

    with httpx.Client(timeout=8.0) as client:
        # 1. Try querying /v1/models or /models
        for m_url in [f"{base_url}/v1/models", f"{base_url}/models"]:
            try:
                m_res = client.get(m_url, headers=headers)
                if m_res.status_code == 200:
                    m_data = m_res.json()
                    if isinstance(m_data, dict) and "data" in m_data and isinstance(m_data["data"], list):
                        discovered_models = [item.get("id") for item in m_data["data"] if isinstance(item, dict) and "id" in item]
                    elif isinstance(m_data, dict) and "models" in m_data and isinstance(m_data["models"], list):
                        discovered_models = [item if isinstance(item, str) else item.get("id", item.get("name")) for item in m_data["models"]]
                    elif isinstance(m_data, list):
                        discovered_models = [item if isinstance(item, str) else item.get("id", item.get("name")) for item in m_data]
                    
                    if discovered_models:
                        models_found = True
                        break
            except Exception as e:
                errors.append(f"{m_url}: {e}")

        # 2. Try probe of transcribe endpoint with a tiny audio probe
        try:
            import io, wave
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\x00\x00' * 1600)
            wav_bytes = buf.getvalue()

            files = {"file": ("probe.wav", wav_bytes, "audio/wav")}
            data = {"model": req.model or "base"}
            resp = client.post(transcribe_url, files=files, data=data, headers=headers)
            
            elapsed_ms = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                msg = f"Connected! Server is responsive and audio probe succeeded ({elapsed_ms}ms)."
                if discovered_models:
                    msg += f" Found {len(discovered_models)} model(s)."
                return {
                    "status": "ok",
                    "message": msg,
                    "models": discovered_models,
                    "latency_ms": elapsed_ms,
                    "endpoint": transcribe_url
                }
            elif resp.status_code == 401:
                return {
                    "status": "error",
                    "message": "Authentication failed (HTTP 401 Unauthorized). Please check your API Key."
                }
            elif resp.status_code in (400, 422):
                resp_text = resp.text[:150]
                return {
                    "status": "ok",
                    "message": f"Connected to Whisper endpoint ({elapsed_ms}ms). Server responded: {resp_text}",
                    "models": discovered_models,
                    "latency_ms": elapsed_ms,
                    "endpoint": transcribe_url
                }
            else:
                errors.append(f"HTTP {resp.status_code} at {transcribe_url}")
        except Exception as e:
            errors.append(f"Probe error: {e}")

        elapsed_ms = int((time.time() - t0) * 1000)
        if models_found:
            return {
                "status": "ok",
                "message": f"Connected to server ({elapsed_ms}ms)! Discovered {len(discovered_models)} model(s).",
                "models": discovered_models,
                "latency_ms": elapsed_ms,
                "endpoint": transcribe_url
            }

        # 3. Check health or root endpoints
        for h_url in [f"{base_url}/health", f"{base_url}/"]:
            try:
                h_res = client.get(h_url, headers=headers)
                if h_res.status_code in (200, 204):
                    return {
                        "status": "ok",
                        "message": f"Server reached at {base_url} (HTTP {h_res.status_code} in {elapsed_ms}ms).",
                        "models": discovered_models,
                        "latency_ms": elapsed_ms,
                        "endpoint": transcribe_url
                    }
            except Exception:
                pass

    detail_err = "; ".join(errors) if errors else "Server unreachable"
    return {
        "status": "error",
        "message": f"Could not connect to Whisper endpoint at {transcribe_url}. Details: {detail_err}"
    }

@router.get("/storage")
def storage_info():
    return get_storage_stats()

@router.post("/storage/clear-cache")
def purge_cache():
    freed = clear_cache()
    return {"status": "ok", "freed_bytes": freed, "freed_formatted": format_size(freed)}

@router.post("/storage/clear-history")
def purge_history():
    freed = clear_history()
    return {"status": "ok", "freed_bytes": freed, "freed_formatted": format_size(freed)}

@router.post("/storage/reset")
def do_factory_reset():
    res = factory_reset()
    return {"status": "ok", "reset_details": res}

@router.post("/rename/preview")
def preview_rename(req: Union[RenamePreviewRequest, List[str]]):
    cfg = load_config()
    if isinstance(req, list):
        file_paths = req
        date_override = None
        date_source = getattr(cfg, "date_source", "smart")
        template = cfg.rename_template
        max_title_length = getattr(cfg, "max_title_length", 50)
        include_names = getattr(cfg, "include_names_in_title", False)
    else:
        file_paths = req.file_paths
        date_override = req.date_override
        date_source = req.date_source or getattr(cfg, "date_source", "smart")
        template = req.template or cfg.rename_template
        max_title_length = req.max_title_length if req.max_title_length is not None else getattr(cfg, "max_title_length", 50)
        include_names = req.include_names if req.include_names is not None else getattr(cfg, "include_names_in_title", False)

    from src.core.paths import get_history_path
    from src.media.renamer import resolve_datetime

    # Load rename history in case files were already auto-renamed once
    history_file = get_history_path() / "renames.json"
    rename_history_map = {}
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as hf:
                h_records = json.load(hf)
                for tx in h_records:
                    if "to" in tx and "from" in tx:
                        rename_history_map[str(Path(tx["to"]).resolve())] = Path(tx["from"]).name
        except Exception:
            pass

    previews = []
    for fp in file_paths:
        p = Path(fp)
        if not p.exists():
            continue
        parent = p.parent
        stem = p.stem
        name = p.name
        json_candidates = [parent / f"{stem}.info.json", parent / f"{name}.info.json"]
        sidecar_json = next((f for f in json_candidates if f.exists()), None)
        ai_title = p.stem
        suggested_slug = None
        date_str = None
        people_list = []
        original_name = rename_history_map.get(str(p.resolve()))

        if sidecar_json and sidecar_json.exists():
            try:
                with open(sidecar_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ai_title = data.get("analysis", {}).get("title") or p.stem
                    suggested_slug = data.get("analysis", {}).get("suggested_filename")
                    date_str = data.get("file", {}).get("metadata", {}).get("creation_time") or data.get("metadata", {}).get("creation_time")
                    people_list = data.get("analysis", {}).get("people_or_subjects", [])
                    if not original_name and "file" in data and isinstance(data["file"], dict):
                        original_name = data["file"].get("name")
            except Exception:
                pass

        if not sidecar_json:
            txt_candidates = [parent / f"{name}.txt", parent / f"{stem}.txt"]
            txt_p = next((f for f in txt_candidates if f.exists()), None)
            if txt_p:
                try:
                    txt_lines = txt_p.read_text(encoding="utf-8").splitlines()
                    if txt_lines:
                        line1 = txt_lines[0].strip()
                        if " — " in line1:
                            txt_orig, txt_ai = line1.split(" — ", 1)
                            if not original_name and txt_orig:
                                original_name = txt_orig.strip()
                            if txt_ai:
                                ai_title = txt_ai.strip()
                        for l in txt_lines:
                            if l.startswith("People:"):
                                people_list = [x.strip() for x in l[len("People:"):].split(",") if x.strip()]
                            elif l.startswith("source:") and not original_name:
                                original_name = l[len("source:"):].strip()
                except Exception:
                    pass

        # If ai_title is still the full current stem and has a timestamp prefix from a previous rename, strip the timestamp
        import re
        if ai_title == p.stem:
            m_pre = re.match(r"^\d{8}[_-]\d{6}[Zz]?[_-](.+)$", ai_title)
            if m_pre:
                ai_title = m_pre.group(1)

        if not original_name:
            original_name = p.name

        dt_local, dt_utc, date_source_used = resolve_datetime(
            original_path=p,
            creation_date=date_str,
            date_override=date_override,
            date_source=date_source,
            original_filename=original_name
        )

        suggested = generate_suggested_name(
            original_path=p,
            ai_title=ai_title,
            creation_date=date_str,
            template=template,
            suggested_slug=suggested_slug,
            people_names=people_list,
            max_title_length=max_title_length,
            include_names_in_title=include_names,
            date_override=date_override,
            date_source=date_source,
            original_filename=original_name
        )
        previews.append({
            "original_path": str(p),
            "current_name": p.name,
            "original_name": original_name,
            "ai_title": ai_title,
            "date_used": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
            "date_source_used": date_source_used,
            "suggested_slug": suggested_slug,
            "suggested_name": suggested,
            "different": suggested != p.name
        })
    return previews

@router.post("/rename/execute")
def apply_rename(req: RenameExecuteRequest):
    orig = Path(req.original_path)
    if not orig.exists():
        raise HTTPException(status_code=404, detail="Original file not found")
    res = execute_rename(orig, req.new_filename, new_creation_date=req.new_creation_date)
    return res

@router.post("/rename/undo")
def undo_rename():
    res = undo_last_rename()
    if not res:
        raise HTTPException(status_code=400, detail="No rename transaction to undo")
    return res

@router.post("/tag/apply")
def tag_file(req: TagRequest):
    p = Path(req.video_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    cfg = load_config()
    tags = {}
    if req.title: tags["title"] = req.title
    if req.description: tags["description"] = req.description
    if req.date: tags["date"] = req.date
    if req.keywords: tags["keywords"] = req.keywords

    try:
        res = apply_metadata_tags(
            p,
            tags=tags,
            create_backup=req.create_backup,
            verify_integrity=req.verify_integrity,
            custom_ffmpeg=cfg.ffmpeg_path
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Drag & Drop Remote Uploads & Downloads ---

@router.post("/upload")
async def upload_video_file(file: UploadFile = File(...)):
    """Accept drag-and-drop video or .srt subtitle upload from client computer."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    ext = Path(file.filename).suffix.lower()
    is_srt = (ext == ".srt")
    if ext not in SUPPORTED_EXTENSIONS and not is_srt:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))} and .srt"
        )

    uploads_dir = get_uploads_dir()
    dest_path = uploads_dir / file.filename

    # If uploading .srt, overwrite existing matching srt so it pairs with the video
    if not is_srt:
        counter = 1
        base_stem = dest_path.stem
        while dest_path.exists():
            dest_path = uploads_dir / f"{base_stem}_{counter}{ext}"
            counter += 1

    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    # Subtitles are staged as context companions and not enqueued as videos
    if is_srt:
        return {
            "status": "uploaded",
            "type": "subtitle",
            "filename": dest_path.name,
            "path": str(dest_path.resolve()),
            "size_bytes": dest_path.stat().st_size,
            "size_formatted": format_size(dest_path.stat().st_size),
            "task_id": None
        }

    # Automatically add video to worker queue
    added = manager.add_to_queue([str(dest_path.resolve())])

    return {
        "status": "uploaded",
        "type": "video",
        "filename": dest_path.name,
        "path": str(dest_path.resolve()),
        "size_bytes": dest_path.stat().st_size,
        "size_formatted": format_size(dest_path.stat().st_size),
        "task_id": added[0].id if added else None
    }

@router.get("/uploads")
def list_uploaded_files():
    """List all files in the uploads staging directory with available sidecars and subtitle pairs."""
    uploads_dir = get_uploads_dir()
    items = []
    
    # Map current tasks for progress info
    task_map = {t.file_path: t for t in manager.queue}

    from src.media.subtitles import find_accompanying_srt

    for p in uploads_dir.iterdir():
        if is_video_file(p):
            stat = p.stat()
            txt_p = p.parent / f"{p.name}.txt"
            json_p = p.parent / f"{p.stem}.info.json"
            xmp_p = p.parent / f"{p.stem}.xmp"
            nfo_p = p.parent / f"{p.stem}.nfo"
            edl_p = p.parent / f"{p.name}.edl"
            acc_srt = find_accompanying_srt(p)

            task = task_map.get(str(p.resolve()))
            is_done = bool(txt_p.exists() or json_p.exists() or nfo_p.exists() or xmp_p.exists())

            items.append({
                "filename": p.name,
                "path": str(p.resolve()),
                "size_bytes": stat.st_size,
                "size_formatted": format_size(stat.st_size),
                "modified": stat.st_mtime,
                "status": task.status if task else ("completed" if is_done else "ready"),
                "stage": task.stage if task else ("Completed" if is_done else "Ready"),
                "progress": task.progress if task else (100 if is_done else 0),
                "has_srt": acc_srt is not None,
                "srt_filename": acc_srt.name if acc_srt else None,
                "sidecars": {
                    "txt": str(txt_p.resolve()) if txt_p.exists() else None,
                    "json": str(json_p.resolve()) if json_p.exists() else None,
                    "xmp": str(xmp_p.resolve()) if xmp_p.exists() else None,
                    "nfo": str(nfo_p.resolve()) if nfo_p.exists() else None,
                    "edl": str(edl_p.resolve()) if edl_p.exists() else None,
                    "srt": str(acc_srt.resolve()) if acc_srt else None
                }
            })

    # Sort newest first
    items.sort(key=lambda x: x["modified"], reverse=True)
    return {"uploads": items}

@router.delete("/uploads/{filename}")
def delete_uploaded_file(filename: str):
    """Delete a specific uploaded file and all its associated sidecars."""
    uploads_dir = get_uploads_dir()
    target = uploads_dir / filename

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Safety check: ensure file is strictly within uploads_dir
    if not str(target.resolve()).startswith(str(uploads_dir.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")

    # Delete video file
    target.unlink()

    # Delete accompanying sidecars
    prefix = filename
    deleted_sidecars = []
    for sidecar in uploads_dir.glob(f"{target.stem}*"):
        if sidecar != target and sidecar.is_file():
            sidecar.unlink()
            deleted_sidecars.append(sidecar.name)

    return {
        "status": "deleted",
        "filename": filename,
        "deleted_sidecars": deleted_sidecars
    }

@router.post("/storage/clear-uploads")
def purge_all_uploads():
    """Purge all files in uploads directory."""
    freed = clear_uploads()
    return {"status": "ok", "freed_bytes": freed, "freed_formatted": format_size(freed)}

@router.get("/download")
def download_file(file_path: str):
    """Download a sidecar or processed video file."""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Requested file does not exist")

    # Return file attachment
    return FileResponse(
        path=str(p.resolve()),
        filename=p.name,
        media_type="application/octet-stream"
    )

class CustomDownloadRequest(BaseModel):
    file_path: str
    output_filename: Optional[str] = None
    embed_tags: bool = True
    embed_subtitles: bool = True
    target_format: str = "original"  # "original" | "mkv"

@router.post("/download/custom-video")
def download_custom_video(req: CustomDownloadRequest):
    """
    Generate and stream a customized video file with embedded metadata tags
    and/or embedded soft subtitles (MKV only, not MP4), optionally renamed.
    """
    uploads_dir = get_uploads_dir()
    p = Path(req.file_path)
    if not p.is_absolute() or not p.exists():
        cand = uploads_dir / p.name
        if cand.exists():
            p = cand

    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    cfg = load_config()

    # Locate sidecars to extract tags
    parent = p.parent
    stem = p.stem
    name = p.name

    json_candidates = [parent / f"{stem}.info.json", parent / f"{name}.info.json"]
    json_p = next((f for f in json_candidates if f.exists()), None)
    
    meta_tags = {}
    if json_p:
        try:
            with open(json_p, "r", encoding="utf-8") as jf:
                jdata = json.load(jf)
            analysis = jdata.get("analysis", {})
            title = analysis.get("title", "")
            summary = analysis.get("summary", "")
            tags = analysis.get("tags", [])
            people = analysis.get("people_or_subjects", [])
            objects = analysis.get("objects", [])
            animals = analysis.get("animals_or_pets", [])
            date_val = jdata.get("file", {}).get("metadata", {}).get("creation_time") or jdata.get("metadata", {}).get("creation_time", "")
            
            people_tags = [f"Person: {x}" for x in people]
            all_keywords = list(dict.fromkeys(tags + people_tags + objects + animals))
            meta_tags = {
                "title": title,
                "description": summary,
                "keywords": "; ".join(all_keywords),
                "date": date_val
            }
        except Exception as e:
            logger.warning(f"Error loading sidecar tags for download: {e}")

    # Fallback to active/recent queue task result if sidecar missing
    if not meta_tags:
        task_match = next((t for t in manager.queue if t.file_path == str(p.resolve())), None)
        if task_match and task_match.result:
            r = task_match.result
            t_tags = r.get("tags", [])
            t_people = r.get("people", [])
            t_objects = r.get("objects", [])
            t_animals = r.get("animals_or_pets", [])
            people_tags = [f"Person: {x}" for x in t_people]
            all_keywords = list(dict.fromkeys(t_tags + people_tags + t_objects + t_animals))
            meta_tags = {
                "title": r.get("title", ""),
                "description": r.get("summary", ""),
                "keywords": "; ".join(all_keywords),
                "date": ""
            }

    # Check for accompanying subtitles (.srt)
    from src.media.subtitles import find_accompanying_srt
    srt_p = find_accompanying_srt(p)

    # Determine container format and extension
    orig_ext = p.suffix.lower()
    target_format = req.target_format.lower()
    if target_format == "mkv" or (req.embed_subtitles and orig_ext == ".mkv"):
        final_ext = ".mkv"
    else:
        final_ext = orig_ext

    # Determine desired download filename
    if req.output_filename and req.output_filename.strip():
        download_name = req.output_filename.strip()
        if not download_name.lower().endswith(final_ext):
            download_name = f"{Path(download_name).stem}{final_ext}"
    else:
        download_name = f"{p.stem}{final_ext}"

    # Build temporary destination
    temp_dir = get_cache_dir() / "downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_out = temp_dir / f"dl_{uuid.uuid4().hex[:8]}_{download_name}"

    # If soft subtitles requested but no .srt file on disk, synthesize temporarily from transcript
    temp_srt_to_clean: Optional[Path] = None
    if not srt_p and req.embed_subtitles:
        transcript = None
        if json_p:
            try:
                with open(json_p, "r", encoding="utf-8") as jf:
                    jdata = json.load(jf)
                    transcript = jdata.get("analysis", {}).get("audio_transcript") or jdata.get("audio_transcript")
            except Exception:
                pass
        if not transcript:
            task_match = next((t for t in manager.queue if t.file_path == str(p.resolve())), None)
            if task_match and task_match.result:
                transcript = task_match.result.get("audio_transcript")
        if transcript:
            try:
                from src.media.subtitles import generate_srt_from_text
                srt_content = generate_srt_from_text(transcript)
                if srt_content.strip():
                    temp_srt_to_clean = temp_dir / f"temp_{uuid.uuid4().hex[:8]}.srt"
                    temp_srt_to_clean.write_text(srt_content, encoding="utf-8")
                    srt_p = temp_srt_to_clean
            except Exception as e:
                logger.warning(f"Could not synthesize temp srt for video download: {e}")

    try:
        from src.media.tagger import create_custom_download_video
        create_custom_download_video(
            source_video_path=p,
            output_path=temp_out,
            metadata_tags=meta_tags,
            srt_path=srt_p,
            embed_tags=req.embed_tags,
            embed_subtitles=req.embed_subtitles,
            target_format=target_format,
            custom_ffmpeg=cfg.ffmpeg_path
        )
    except Exception as e:
        logger.error(f"Error creating custom download: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to prepare customized video: {str(e)}")
    finally:
        if temp_srt_to_clean and temp_srt_to_clean.exists():
            try:
                temp_srt_to_clean.unlink()
            except Exception:
                pass

    return FileResponse(
        path=str(temp_out.resolve()),
        filename=download_name,
        media_type="application/octet-stream"
    )

class UpdateObjectsRequest(BaseModel):
    file_path: str
    objects: List[str]

@router.post("/results/update-objects")
def update_video_objects(req: UpdateObjectsRequest):
    """
    Update object tags for a video and sync them into .info.json, .xmp, .nfo, and .txt sidecars.
    """
    uploads_dir = get_uploads_dir()
    p = Path(req.file_path)
    if not p.is_absolute() or not p.exists():
        cand = uploads_dir / p.name
        if cand.exists():
            p = cand

    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    parent = p.parent
    stem = p.stem
    name = p.name
    clean_objects = [o.strip() for o in req.objects if o.strip()]

    # 1. Update .info.json
    json_candidates = [parent / f"{stem}.info.json", parent / f"{name}.info.json"]
    json_p = next((f for f in json_candidates if f.exists()), None)
    if json_p:
        try:
            with open(json_p, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            analysis = data.setdefault("analysis", {})
            analysis["objects"] = clean_objects
            existing_tags = analysis.setdefault("tags", [])
            for obj in clean_objects:
                if obj.lower() not in [t.lower() for t in existing_tags]:
                    existing_tags.append(obj)
            with open(json_p, "w", encoding="utf-8") as jf:
                json.dump(data, jf, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error updating JSON sidecar objects: {e}")

    # 2. Update .xmp
    xmp_candidates = [parent / f"{stem}.xmp", parent / f"{name}.xmp"]
    xmp_p = next((f for f in xmp_candidates if f.exists()), None)
    if xmp_p:
        try:
            import re
            content = xmp_p.read_text(encoding="utf-8")
            obj_items = "".join([f"\n            <rdf:li>Object:{o}</rdf:li>" for o in clean_objects])
            if "</rdf:Bag>" in content:
                content = re.sub(r'\s*<rdf:li>Object:[^<]+</rdf:li>', '', content)
                content = content.replace("</rdf:Bag>", f"{obj_items}\n          </rdf:Bag>")
                xmp_p.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Error updating XMP sidecar objects: {e}")

    return {
        "status": "ok",
        "objects": clean_objects,
        "message": f"Updated {len(clean_objects)} object tags across sidecars"
    }

@router.get("/results")
def get_video_results(file_path: str):
    """
    Retrieve parsed analysis results, sidecars, and metadata for a video file.
    Works for both locally scanned videos and remote staged uploads.
    """
    uploads_dir = get_uploads_dir()
    p = Path(file_path)

    # If relative filename given, check in uploads_dir
    if not p.is_absolute() or not p.exists():
        upload_cand = uploads_dir / p.name
        if upload_cand.exists():
            p = upload_cand

    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    parent = p.parent
    stem = p.stem
    name = p.name

    # Look for sidecars
    json_candidates = [parent / f"{stem}.info.json", parent / f"{name}.info.json"]
    json_p = next((f for f in json_candidates if f.exists()), None)

    txt_candidates = [parent / f"{name}.txt", parent / f"{stem}.txt"]
    txt_p = next((f for f in txt_candidates if f.exists()), None)

    xmp_candidates = [parent / f"{stem}.xmp", parent / f"{name}.xmp"]
    xmp_p = next((f for f in xmp_candidates if f.exists()), None)

    nfo_candidates = [parent / f"{stem}.nfo", parent / f"{name}.nfo"]
    nfo_p = next((f for f in nfo_candidates if f.exists()), None)

    edl_candidates = [parent / f"{name}.edl", parent / f"{stem}.edl"]
    edl_p = next((f for f in edl_candidates if f.exists()), None)

    srt_candidates = [
        parent / f"{stem}.srt",
        parent / f"{name}.srt",
        parent / f"{stem}.en.srt",
        parent / f"{stem}.eng.srt"
    ]
    srt_p = next((f for f in srt_candidates if f.exists() and f.stat().st_size > 0), None)

    title = ""
    summary = ""
    events = []
    people = []
    animals_or_pets = []
    objects = []
    audio_transcript = None
    suggested_filename = ""
    provider = ""
    model = ""
    processed_at = None
    creation_time = None

    # 1. Parse .info.json if available
    if json_p:
        try:
            with open(json_p, "r", encoding="utf-8") as jf:
                jdata = json.load(jf)
                analysis = jdata.get("analysis", {})
                title = analysis.get("title", "")
                summary = analysis.get("summary", "")
                events = analysis.get("events", [])
                tags = analysis.get("tags", [])
                people = analysis.get("people_or_subjects", [])
                animals_or_pets = analysis.get("animals_or_pets", [])
                objects = analysis.get("objects", [])
                audio_transcript = analysis.get("audio_transcript")
                suggested_filename = analysis.get("suggested_filename", "")
                provider = analysis.get("provider", "")
                model = analysis.get("model", "")
                processed_at = analysis.get("processed_at")
                creation_time = jdata.get("file", {}).get("metadata", {}).get("creation_time") or jdata.get("metadata", {}).get("creation_time")
        except Exception as e:
            logger.warning(f"Error reading JSON sidecar {json_p}: {e}")

    # 2. Fallback to active/recent queue task result
    if not title or not summary:
        task_match = next((t for t in manager.queue if t.file_path == str(p.resolve())), None)
        if task_match and task_match.result:
            title = title or task_match.result.get("title", "")
            summary = summary or task_match.result.get("summary", "")
            tags = tags or task_match.result.get("tags", [])
            animals_or_pets = animals_or_pets or task_match.result.get("animals_or_pets", [])
            objects = objects or task_match.result.get("objects", [])
            people = people or task_match.result.get("people", [])
            suggested_filename = suggested_filename or task_match.result.get("suggested_filename", "")

    if not audio_transcript:
        task_match = next((t for t in manager.queue if t.file_path == str(p.resolve())), None)
        if task_match and task_match.result:
            audio_transcript = task_match.result.get("audio_transcript")

    if not creation_time:
        try:
            stat = p.stat()
            creation_time = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except Exception:
            pass

    # 3. Read raw .txt sidecar snippet if available
    raw_txt = ""
    if txt_p:
        try:
            raw_txt = txt_p.read_text(encoding="utf-8")
            if not summary:
                summary = raw_txt
        except Exception:
            pass

    # Compute formatted suggested filename matching user's active Settings template
    from src.media.renamer import generate_suggested_name
    cfg = load_config()
    orig_name_from_json = jdata.get("file", {}).get("name") if 'jdata' in locals() and isinstance(jdata, dict) else None
    formatted_suggested_name = generate_suggested_name(
        original_path=p,
        ai_title=title or stem,
        creation_date=str(creation_time) if creation_time else None,
        template=cfg.rename_template,
        suggested_slug=suggested_filename,
        collection_name=p.parent.name if p.parent else "",
        people_names=people,
        max_title_length=getattr(cfg, "max_title_length", 50),
        include_names_in_title=getattr(cfg, "include_names_in_title", False),
        date_override=getattr(cfg, "default_date_override", None),
        date_source=getattr(cfg, "date_source", "smart"),
        original_filename=orig_name_from_json
    )

    import urllib.parse
    has_subtitles = bool(srt_p) or bool(audio_transcript)
    srt_download_url = None
    if srt_p:
        srt_download_url = f"/api/download?file_path={urllib.parse.quote(str(srt_p.resolve()))}"
    elif audio_transcript:
        srt_download_url = f"/api/download/srt?file_path={urllib.parse.quote(str(p.resolve()))}"

    return {
        "status": "ok",
        "filename": name,
        "file_path": str(p.resolve()),
        "title": title or stem,
        "summary": summary,
        "events": events,
        "tags": tags,
        "tags_string": ", ".join(tags) if tags else "",
        "people": people,
        "animals_or_pets": animals_or_pets,
        "objects": objects,
        "audio_transcript": audio_transcript,
        "suggested_filename": formatted_suggested_name,
        "ai_slug": suggested_filename or stem,
        "creation_time": creation_time,
        "provider": provider,
        "model": model,
        "processed_at": processed_at,
        "raw_txt": raw_txt,
        "sidecars": {
            "txt": {
                "exists": bool(txt_p),
                "path": str(txt_p.resolve()) if txt_p else None,
                "filename": txt_p.name if txt_p else None,
                "url": f"/api/download?file_path={urllib.parse.quote(str(txt_p.resolve()))}" if txt_p else None
            },
            "json": {
                "exists": bool(json_p),
                "path": str(json_p.resolve()) if json_p else None,
                "filename": json_p.name if json_p else None,
                "url": f"/api/download?file_path={urllib.parse.quote(str(json_p.resolve()))}" if json_p else None
            },
            "xmp": {
                "exists": bool(xmp_p),
                "path": str(xmp_p.resolve()) if xmp_p else None,
                "filename": xmp_p.name if xmp_p else None,
                "url": f"/api/download?file_path={urllib.parse.quote(str(xmp_p.resolve()))}" if xmp_p else None
            },
            "nfo": {
                "exists": bool(nfo_p),
                "path": str(nfo_p.resolve()) if nfo_p else None,
                "filename": nfo_p.name if nfo_p else None,
                "url": f"/api/download?file_path={urllib.parse.quote(str(nfo_p.resolve()))}" if nfo_p else None
            },
            "edl": {
                "exists": bool(edl_p),
                "path": str(edl_p.resolve()) if edl_p else None,
                "filename": edl_p.name if edl_p else None,
                "url": f"/api/download?file_path={urllib.parse.quote(str(edl_p.resolve()))}" if edl_p else None
            },
            "srt": {
                "exists": has_subtitles,
                "path": str(srt_p.resolve()) if srt_p else None,
                "filename": srt_p.name if srt_p else f"{stem}.srt",
                "url": srt_download_url
            }
        },
        "video": {
            "filename": name,
            "path": str(p.resolve()),
            "url": f"/api/download?file_path={urllib.parse.quote(str(p.resolve()))}"
        }
    }

@router.get("/download/srt")
def download_srt(file_path: str):
    """
    Download a separate .srt subtitle file for a video.
    Returns existing .srt if present, or dynamically synthesizes .srt from dialogue transcript.
    """
    p = Path(file_path)
    parent = p.parent
    stem = p.stem

    srt_candidates = [
        parent / f"{stem}.srt",
        parent / f"{p.name}.srt",
        parent / f"{stem}.en.srt",
        parent / f"{stem}.eng.srt"
    ]
    for cand in srt_candidates:
        if cand.exists() and cand.stat().st_size > 0:
            return FileResponse(
                path=str(cand.resolve()),
                filename=cand.name,
                media_type="text/plain; charset=utf-8"
            )

    # If no srt on disk, extract transcript from .info.json
    json_candidates = [parent / f"{stem}.info.json", parent / f"{p.name}.info.json"]
    transcript = None
    for cand in json_candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data.get("analysis"), dict):
                        transcript = data["analysis"].get("audio_transcript")
                    if not transcript:
                        transcript = data.get("audio_transcript")
                    if transcript:
                        break
            except Exception:
                pass

    if not transcript:
        # Check active queue task
        task_match = next((t for t in manager.queue if t.file_path == str(p.resolve())), None)
        if task_match and task_match.result:
            transcript = task_match.result.get("audio_transcript")

    if not transcript:
        raise HTTPException(status_code=404, detail="No speech transcript available to generate .srt")

    from src.media.subtitles import generate_srt_from_text
    srt_content = generate_srt_from_text(transcript)
    from fastapi.responses import Response
    return Response(
        content=srt_content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.srt"'}
    )


# --- Facial Recognition Endpoints ---

@router.get("/faces")
def list_faces():
    """List all tracked face identities, auto-generated clusters, and thumbnail links."""
    faces = face_registry.get_all()
    return {"faces": faces, "total": len(faces)}

@router.get("/faces/export")
def export_faces_database():
    """Export the entire faces registry and thumbnail photos as a downloadable zip file."""
    import tempfile
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"faces_database_{timestamp}.zip"
    tmp_zip = Path(tempfile.gettempdir()) / zip_filename

    face_registry.export_database_zip(tmp_zip)
    if not tmp_zip.exists():
        raise HTTPException(status_code=500, detail="Failed to create database archive")

    return FileResponse(
        path=str(tmp_zip.resolve()),
        filename=zip_filename,
        media_type="application/zip"
    )

@router.post("/faces/import")
async def import_faces_database(file: UploadFile = File(...), merge: bool = True):
    """Import and restore face database from an uploaded .zip archive."""
    import tempfile
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip database archives are supported")

    tmp_path = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4().hex}.zip"
    try:
        with open(tmp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        count = face_registry.import_database_zip(tmp_path, merge=merge)
        return {"status": "ok", "message": f"Successfully imported {count} face records.", "imported_count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to import database: {str(e)}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

@router.post("/faces/{person_id}/rename")
def rename_face(person_id: str, req: RenamePersonRequest):
    """Rename a face cluster (e.g. Person_01 -> Grandma Betty) and retroactively update video sidecars."""
    try:
        res = face_registry.rename_person(person_id, req.new_name, update_sidecars=req.update_sidecars)
        return res
    except KeyError:
        raise HTTPException(status_code=404, detail="Person ID not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/faces/merge")
def merge_faces(req: MergePersonsRequest):
    """Merge two person clusters into one identity."""
    try:
        res = face_registry.merge_persons(req.source_id, req.target_id)
        return res
    except KeyError:
        raise HTTPException(status_code=404, detail="One or both Person IDs not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/faces/{person_id}")
def delete_face(person_id: str):
    """Delete a face cluster identity."""
    ok = face_registry.delete_person(person_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Person ID not found")
    return {"status": "deleted", "person_id": person_id}

@router.post("/faces/clear")
def clear_all_faces():
    """Clear all registered individuals and thumbnails from the face database."""
    cleared = face_registry.clear_all()
    return {"status": "cleared", "cleared_count": cleared}

class FaceReindexRequest(BaseModel):
    max_distance: Optional[float] = None
    confidence: Optional[float] = None

@router.post("/faces/reindex")
def reindex_faces(req: Optional[FaceReindexRequest] = None):
    """
    Re-evaluate and cluster existing face identities using the active distance/similarity threshold.
    Merges matching identities, combines video references, and consolidates top-quality face shots.
    """
    cfg = load_config()
    if req:
        if req.max_distance is not None:
            cfg.face_max_distance = float(req.max_distance)
            cfg.face_match_threshold = max(0.01, min(0.99, 1.0 - float(req.max_distance)))
        if req.confidence is not None:
            cfg.face_detection_confidence = float(req.confidence)
        if req.max_distance is not None or req.confidence is not None:
            save_config(cfg)

    thresh = cfg.face_match_threshold
    if hasattr(cfg, "face_max_distance") and cfg.face_max_distance is not None:
        thresh = 1.0 - cfg.face_max_distance
    res = face_registry.recluster_and_reindex(threshold=thresh)
    res["active_threshold"] = thresh
    res["active_max_distance"] = cfg.face_max_distance
    return res

@router.post("/faces/auto-guess-names")
def auto_guess_face_names():
    """
    Use AI descriptions and summaries from processed video sidecars to guess
    and assign names to unnamed face clusters, preserving user-customized identities.
    """
    matches = face_registry.auto_guess_all_unnamed_faces()
    return {
        "status": "ok",
        "matches_count": len(matches),
        "matches": matches
    }

@router.get("/faces/thumbnail/{filename}")
def get_face_thumbnail(filename: str):
    """Serve a face thumbnail crop image."""
    faces_dir = get_faces_dir()
    thumb_path = faces_dir / "thumbs" / filename
    if not thumb_path.exists() or not thumb_path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(path=str(thumb_path.resolve()), media_type="image/jpeg")

@router.post("/faces/test-external")
def test_compreface_connection(req: TestCompreFaceRequest):
    """Test connection to an external CompreFace server."""
    import httpx
    url = req.url.rstrip("/") + "/api/v1/recognition/subjects"
    headers = {"x-api-key": req.api_key}
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                subjects = data.get("subjects", [])
                return {"status": "ok", "message": f"Connected! Found {len(subjects)} registered subject(s).", "subjects": subjects}
            else:
                return {"status": "error", "message": f"Server returned HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {str(e)}"}

