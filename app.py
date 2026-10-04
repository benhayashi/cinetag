#!/usr/bin/env python3
import argparse
import sys
import uvicorn
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from src.core.config import load_config
from src.core.paths import find_binary, is_portable_mode, is_docker_mode
from src.ai.whisper_service import patch_pyav_metadata_errors_if_needed

patch_pyav_metadata_errors_if_needed()

def main():
    parser = argparse.ArgumentParser(
        description="CineTag - Local-first video understanding & metadata tool"
    )
    parser.add_argument("path", nargs="?", help="Optional video folder path to process via CLI")
    parser.add_argument("--host", default=None, help="Host to bind server (default: from config or 127.0.0.1; use 0.0.0.0 for LAN access, which requires an access token)")
    parser.add_argument("--port", type=int, default=None, help="Port for server (default: from config or 5555)")
    parser.add_argument("--portable", action="store_true", help="Force portable mode (stores all data in ./data)")
    parser.add_argument("--cli", action="store_true", help="Run directly in CLI mode instead of web server")
    args = parser.parse_args()

    if args.portable:
        import os
        os.environ["PORTABLE"] = "1"

    config = load_config()

    # Pre-flight diagnostic check
    ffmpeg_bin = find_binary("ffmpeg", config.ffmpeg_path)
    ffprobe_bin = find_binary("ffprobe", config.ffprobe_path)

    print("=" * 60)
    print("🎞️  CineTag - AI Video Organizer")
    print("=" * 60)
    print(f"• Mode: {'Portable (./data)' if is_portable_mode() else ('Docker Container' if is_docker_mode() else 'System Installed')}")
    print(f"• FFmpeg:  {'Found (' + ffmpeg_bin + ')' if ffmpeg_bin else '⚠️ NOT FOUND in PATH (install ffmpeg or place in bin/)'}")
    print(f"• FFprobe: {'Found (' + ffprobe_bin + ')' if ffprobe_bin else '⚠️ NOT FOUND in PATH'}")
    print(f"• Vision Backend: {config.vision_provider} ({config.ollama_model if config.vision_provider == 'ollama' else config.openai_compatible_model})")
    print(f"• Whisper Audio:  {'Enabled (' + config.whisper_model + ')' if config.transcribe_audio else 'Disabled'}")
    print("=" * 60)

    # CLI processing mode
    if args.cli and args.path:
        target_dir = Path(args.path)
        if not target_dir.is_dir():
            print(f"Error: {target_dir} is not a valid directory.")
            sys.exit(1)
        
        from src.server.queue_manager import manager
        from src.media.probe import is_video_file
        
        files = [str(p) for p in target_dir.glob("**/*") if is_video_file(p)]
        print(f"Found {len(files)} video clips in {target_dir}")
        manager.add_to_queue(files)
        manager.start()
        
        print("Processing queue in background. Press Ctrl+C to stop.")
        try:
            while manager.is_running:
                status = manager.get_status()
                counts = status["counts"]
                cur = status["current_task"]
                if cur:
                    print(f"\r[{cur['filename']}] {cur['stage']} ({cur['progress']}%) - Completed: {counts['completed']}/{counts['total']}", end="")
                if counts["completed"] + counts["failed"] >= counts["total"] and counts["total"] > 0:
                    break
                import time
                time.sleep(1.0)
            print("\nBatch processing finished.")
        except KeyboardInterrupt:
            print("\nStopped by user.")
        return

    # Web Dashboard Mode (Default)
    host = args.host or config.host
    port = args.port or config.port

    # Tell the app which interface it is bound to so it can enforce the access token for LAN use.
    import os
    os.environ["CINETAG_BIND_HOST"] = host
    from src.core.config import is_loopback_host

    shown_host = "localhost" if is_loopback_host(host) else host
    print(f"\n🚀 Starting Web Dashboard at: http://{shown_host}:{port}")
    if is_loopback_host(host):
        print("🔒 Listening on this computer only. Use --host 0.0.0.0 (or set 'host' in config) to allow LAN access.")
    else:
        from src.server.app import app as _app
        token = _app.state.access_token
        if token:
            print("🌐 LAN access enabled — an access token is required.")
            print(f"   Token: {token}")
            print(f"   One-click login URL: http://<this-computer-ip>:{port}/?token={token}")
        else:
            print("🌐 LAN access enabled (no access token required).")
    print("Open this URL in your web browser to manage footage.\n")

    uvicorn.run("src.server.app:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    main()
