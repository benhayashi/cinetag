# 🎞️ CineTag

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Local & Private](https://img.shields.io/badge/Privacy-100%25%20Offline%20First-success.svg)](#-privacy--local-first-design)

> **Private, local-first media intelligence dashboard: automated video description, speech transcription, facial indexing, sidecar metadata generation, and safe home video organization.**

**CineTag** is an open-source, private media intelligence dashboard built specifically for family archives, GoPro / action camera clips, phone recordings, and large home video collections. It combines visual reasoning from local Vision-Language Models (via **Ollama**, **LM Studio**, **LocalAI**, **vLLM**, or any OpenAI-compatible server) with speech transcription via **Whisper** (embedded local faster-whisper or networked Whisper servers across any home server, NAS, or homelab) and local **Face Recognition** to understand, describe, tag, and organize video clips — keeping 100% of your private memories offline.

---

## 🌟 Key Features

- **🔒 100% Local-First & Private**: Works completely offline with local Vision models (e.g., `qwen2.5vl`, `llama3.2-vision`, `minicpm-v`) and local Whisper. Zero telemetry, no external accounts required, and no data leaves your network.
- **📁 Dual Intake Workflows**:
  - **Mode A (In-Place on Host / Direct NAS Mount)**: Drag & drop local folders or video clips directly into the browser, or use the native host file picker. Media is processed directly on your storage or mounted network share with **zero duplicate file writes**.
  - **Mode B (Remote Upload / LAN Access)**: Access the dashboard from any computer, tablet, or phone on your local network. Drag & drop clips to stage them, process them, and download generated sidecars or tagged videos.
- **🎙️ Speech Transcription & Subtitles**:
  - **Built-in Local Whisper**: Embedded `faster-whisper` (`tiny` up to `large-v3`) running locally on CPU or GPU.
  - **Networked Remote Whisper APIs**: Connect to any OpenAI-compatible Whisper server or container on your LAN (e.g., `speaches`, `faster-whisper-server`, `whisper-asr-webservice`, or LocalAI).
  - Automatically exports full-dialogue `.srt` subtitle sidecars for immediate playback.
  - Optional automatic spoken language translation to English.
- **👤 Facial Indexing & Person Tagging**:
  - Automatically extracts and clusters faces across clips using local ONNX vision models.
  - Name individuals once; future clips automatically detect and tag recognized people.
  - AI Description Face Guessing: Optionally correlates AI visual observations with known faces.
  - Export and import your face recognition database across machines and backups.
- **🧠 Smart AI Context & Description Guidance**:
  - Add batch-specific guidance (e.g., event type, locations, key people to look for).
  - Automatically handles high-context video prompts with intelligent context window management (`num_ctx = 16384` default) and self-healing automatic retries.
- **📄 Non-Destructive Standard Sidecars**:
  - `video.mp4.txt`: Timestamped narrative summary with starred key moments (★).
  - `video.srt`: Synchronized subtitle sidecar for immediate playback in VLC, Plex, Jellyfin, or Emby.
  - `video.info.json`: Comprehensive structured metadata for scripts and cataloging tools.
  - `video.nfo`: Kodi / Jellyfin / Emby compatible movie & home video metadata.
  - `video.xmp`: Standard Adobe XMP sidecar for DigiKam, Darktable, and Adobe Bridge.
  - `video.mp4.edl`: Edit Decision List timeline markers for DaVinci Resolve.
- **🏷️ Safe Renaming with 1-Click Rollback**:
  - Proposes chronological, highly descriptive filenames (e.g., `20240518_183000_Kids_Birthday_Party.mp4`).
  - Automatically renames all accompanying sidecars alongside the video.
  - Every rename is recorded in an undo journal for instant 1-click reversal.
- **🛡️ Container Tagging with Integrity Verification**:
  - Safely write title, description, and keywords directly into MP4/MOV containers via FFmpeg stream-copy (no quality loss).
  - Verifies duration and stream integrity before finalizing, with automatic `.bak` safety backups and cleanup.
- **⚙️ Machine-Readable Configuration**:
  - Export and import your entire setup as a portable JSON configuration file.

---

## 🖥️ System Architecture & Compatibility

CineTag is designed to fit seamlessly into any homelab, home server, or desktop environment:

| Component | Supported Environments & Engines |
| :--- | :--- |
| **Host OS** | Linux (Ubuntu, Debian, Arch, Fedora), Windows 10 / 11, macOS |
| **Home Servers & NAS** | Docker, unRAID, TrueNAS (SCALE / Core), Proxmox VE (LXC or VM), Synology DSM, QNAP, CasaOS, Cosmos, Umbrel, OpenMediaVault, or bare-metal Linux |
| **Storage Protocols** | Direct NVMe/SSD/HDD, SMB / CIFS, NFS, SSHFS, GVFS / FUSE network mounts |
| **Vision AI (VLM)** | **Ollama**, **LM Studio**, **LocalAI**, **vLLM**, text-generation-webui, llama.cpp server, or Cloud fallback (Gemini, Claude, OpenAI) |
| **Speech-to-Text** | Local embedded `faster-whisper`, or remote OpenAI-compatible Whisper (`speaches`, `faster-whisper-server`, `whisper-asr-webservice`) |
| **Face Recognition** | Local embedded ONNX (YuNet + SFace) or CompreFace |

---

## 🚀 Quick Start & Deployment

### Option 1: Docker / Docker Compose (Recommended for Home Servers & NAS)

The included Docker configuration runs out of the box with FFmpeg pre-installed and volume mappings for persistent configuration and host video storage.

#### 1. Clone the repository
```bash
git clone https://github.com/benhayashi/cinetag.git
cd cinetag
```

#### 2. Configure media paths
Set `MEDIA_DIR` to the location of your video library on your host or NAS:
```bash
export MEDIA_DIR="/path/to/your/videos"
# e.g., on unRAID:  export MEDIA_DIR="/mnt/user/family_videos"
# e.g., on TrueNAS: export MEDIA_DIR="/mnt/pool/media/videos"
# e.g., on Linux:   export MEDIA_DIR="/mnt/nas/videos"
```

#### 3. Start the container
```bash
docker compose up -d
```

- Open **`http://localhost:5555`** (or `http://your-server-ip:5555`).
- Video files in your media folder will be accessible inside the container at `/media`.
- Application configuration, logs, and face databases persist in `./data`.
- To reach an AI service (Ollama, LM Studio, etc.) running on the host machine from inside Docker, point the API URL in Settings to `http://host.docker.internal:11434`.

---

### Option 2: Ubuntu / Debian / Linux (Native)

#### Prerequisites
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg zenity git
```

#### 1. Clone & Launch
```bash
git clone https://github.com/benhayashi/cinetag.git
cd cinetag

# Launch using the automated launcher script:
./run.sh
```
`run.sh` automatically creates a Python virtual environment (`.venv`), installs all required dependencies, and starts the server on port 5555.

#### 2. How to Update
```bash
./update.sh
```
`update.sh` pulls the latest code from GitHub, applies any updated dependencies, and preserves all your settings and databases.

---

### Option 3: Windows 10 / 11 (Native)

#### Prerequisites
1. **Python 3.10+**: Download from [python.org](https://www.python.org/downloads/) (ensure **"Add Python to PATH"** is checked during installation).
2. **Git for Windows**: Download from [git-scm.com](https://git-scm.com/).
3. **FFmpeg**: Install quickly using Windows Package Manager:
   ```powershell
   winget install Gyan.FFmpeg
   ```
   *(Or place `ffmpeg.exe` and `ffprobe.exe` directly inside the `bin/` folder of this project).*

#### 1. Launch
Double-click **`run.bat`** (or open Command Prompt / PowerShell in the folder and run `run.bat`).
The script automatically sets up the `.venv` virtual environment, installs dependencies, and opens the application.

#### 2. How to Update
Double-click **`update.bat`**. The script runs `git pull`, updates packages, and notifies you when complete.

---

### Option 4: macOS (Native)

#### Prerequisites
Install dependencies using [Homebrew](https://brew.sh/):
```bash
brew install ffmpeg python git
```

#### Launch & Update
- **Launch**: `./run.sh`
- **Update**: `./update.sh`

---

## 🤖 Configuring AI & Audio Backends

CineTag gives you full flexibility to run models locally on your workstation or offload compute to any networked server or homelab GPU host.

### 1. Vision & Multimodal Reasoning (VLM)

#### Ollama (Local or Networked Server)
1. Install [Ollama](https://ollama.com/) on your local machine or network GPU server.
2. Pull a vision model:
   ```bash
   ollama pull qwen2.5vl
   # or: ollama pull llama3.2-vision
   # or: ollama pull minicpm-v
   ```
3. In CineTag Settings ⚙️ -> **Vision & Reasoning Backend**:
   - Provider: **Ollama**
   - Host URL: `http://localhost:11434` (or `http://your-gpu-server-ip:11434`)
   - Context Window (`num_ctx`): Default is **16,384 tokens** (recommended for multi-frame video analysis). CineTag automatically scales context up and retries if a video's visual tokens exceed the buffer.
4. Click **Test & Refresh Models** to verify the connection.

#### OpenAI-Compatible Local Servers (LM Studio, LocalAI, vLLM)
1. Launch your preferred inference server with a vision model loaded (e.g., LM Studio, LocalAI, vLLM).
2. In CineTag Settings ⚙️:
   - Provider: **LM Studio / OpenAI-Compatible**
   - Server Base URL: `http://localhost:1234/v1` (or `http://your-server-ip:port/v1`)
   - Model Name: Your loaded model identifier (or click **Test Connection** to auto-detect).

#### Cloud Providers (Optional Fallback)
If you prefer cloud models or don't have a local GPU, CineTag optionally supports Google Gemini, Anthropic Claude, and OpenAI GPT-4o. Enter your API key under **Cloud Fallback** in Settings.

---

### 2. Speech-to-Text & Subtitles (Whisper)

- **Local Built-in (faster-whisper)**:
  - Runs 100% locally on CPU or GPU without external servers.
  - Choose model size from `tiny` to `large-v3` depending on available hardware.
- **Networked Remote Whisper Server**:
  - Connect to any OpenAI-compatible Whisper container or service running on your LAN (e.g., `speaches`, `faster-whisper-server`, `whisper-asr-webservice`, or LocalAI).
  - In Settings ⚙️, select **Remote Server (OpenAI-Compatible / Docker / Homelab NAS)**.
  - Enter the server address (e.g., `http://192.168.1.100:9000/v1` or `http://nas-server:9000`).
  - Click **⚡ Test Connection & Fetch Models** to verify reachability.

---

## 🔒 Network Access & Security

- **Native installs bind to `127.0.0.1` by default** (only reachable from the same machine). To use CineTag from other devices, run `python app.py --host 0.0.0.0` (or set `host` in `config.json`).
- **LAN access token (currently disabled by default; set `CINETAG_REQUIRE_TOKEN=1` to enable).** When the bind address is not loopback, a token is read from `CINETAG_TOKEN`, then `config.json` (`access_token`), otherwise auto-generated and saved. It is printed at startup (Docker: `docker logs <container>`); open `http://<server>:5555/?token=<token>` once to sign the browser in.
- **Docker** keeps `0.0.0.0` inside the container, so the token applies there too. Set `CINETAG_TOKEN` in your compose file for a fixed value.
- API keys are masked (`********`) in the UI/API and omitted from config exports unless `?include_secrets=true`.
- File downloads are limited to uploads and files currently in the queue.

## 📁 Network Shares & NAS Storage Workflows

When your video archive resides on a Network Attached Storage (NAS) or file server:

### Direct Network Mounts (Mode A - Recommended)
1. Mount your network share (SMB/CIFS or NFS) to your local file system:
   - **Linux**: Mount via `/etc/fstab` or file manager (e.g. `/mnt/nas/videos`).
   - **Windows**: Map network drive to a drive letter (e.g. `Z:\Videos`).
   - **macOS**: Connect to server via Finder (`smb://nas-server/videos`).
2. In CineTag, simply select or drag-and-drop the mounted directory into Mode A.
3. CineTag reads files directly, creates sidecars adjacent to each video, and performs direct metadata updates with **zero network duplication**.

### Remote Web Intake (Mode B)
If you run CineTag as a central headless Docker container on your server:
1. Map your video share directly into the container via `docker-compose.yml` (`MEDIA_DIR`).
2. Users anywhere on the home network can access the dashboard via browser, upload videos to the staging queue, process them, and download generated sidecars or tagged media.

---

## 📂 Project Structure

```text
cinetag/
├── app.py                 # FastAPI application & CLI entrypoint
├── run.sh                 # Linux/macOS 1-click launcher
├── run.bat                # Windows 1-click launcher
├── update.sh              # Linux/macOS 1-command auto-updater
├── update.bat             # Windows 1-click auto-updater
├── Dockerfile             # Multi-stage production container
├── docker-compose.yml     # Turnkey Docker deployment
├── requirements.txt       # Python dependencies
├── LICENSE                # MIT License
├── src/
│   ├── ai/                # Vision and Whisper providers (Ollama, LM Studio, Remote Whisper)
│   ├── core/              # Configuration, path management, and models
│   ├── faces/             # Facial detection, embedding extraction, and clustering
│   ├── media/             # FFmpeg wrapper, frame extraction, audio extraction, probe
│   ├── metadata/          # Sidecar generators (.txt, .srt, .info.json, .nfo, .xmp, .edl)
│   ├── server/            # REST API endpoints, background queue manager, and logging
│   └── web/               # Responsive HTML5 dashboard, CSS, and vanilla JS
└── tests/                 # Comprehensive automated unit & integration test suite
```

---

## 🧪 Running Automated Tests

Run the full pytest suite:

```bash
# On Linux/macOS:
source .venv/bin/activate
pytest -v tests/

# On Windows:
call .venv\Scripts\activate.bat
pytest -v tests/
```

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
