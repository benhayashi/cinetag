# 🎞️ CineTag

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![Local & Private](https://img.shields.io/badge/Privacy-100%25%20Offline%20First-success.svg)](#-privacy--local-first-design)

> **Local-first video understanding, automatic sidecar metadata generation, speech transcription, facial indexing, and safe media library organization.**

**CineTag** is an open-source, private media intelligence dashboard built specifically for family archives, GoPro clips, phone recordings, and large home video collections. It combines visual reasoning from local Vision-Language Models (via **Ollama** or **LM Studio**) with speech transcription via **Whisper** (built-in or remote Whisper servers on TrueNAS / LAN) and local **Face Recognition** to understand, describe, tag, and organize video clips — keeping 100% of your private memories offline.

---

## 🌟 Key Features

- **🔒 100% Local-First & Private**: Works out of the box with local Ollama models (e.g., `qwen2.5-coder`, `llama3.2-vision`, `qwen2.5vl`, `minicpm-v`) and local Whisper. No mandatory cloud accounts or external subscriptions.
- **📁 Dual Intake Workflows**:
  - **Mode A (In-Place on Host)**: Drag & drop local folders or video clips directly into the browser, or use the native host file/folder picker. Media is processed directly on your storage with **zero file duplication**.
  - **Mode B (Remote Upload / LAN)**: Access the dashboard from any computer, tablet, or phone on your local network. Drag & drop clips to stage them, process them, and download generated sidecars or tagged videos.
- **🎙️ Speech Transcription & Subtitles**:
  - Integrated local **faster-whisper** (`tiny` up to `large-v3`).
  - Native support for **Remote Whisper APIs** (such as `hwds12/whisper-server` or `speaches` on **TrueNAS SCALE** or unRAID).
  - Automatically exports full-dialogue `.srt` subtitle sidecars.
- **👤 Facial Indexing & Person Tagging**:
  - Automatically extracts and clusters faces across clips.
  - Name family members once; future clips automatically detect and tag recognized people.
  - AI Description Face Guessing: Optionally matches AI visual observations to known faces.
  - Export and import your face recognition database across machines.
- **📄 Non-Destructive Standard Sidecars**:
  - `video.mp4.txt`: Timestamped narrative summary with starred key moments (★).
  - `video.srt`: Synchronized subtitle sidecar for immediate playback in VLC, Plex, or Jellyfin.
  - `video.info.json`: Comprehensive structured metadata for scripts and cataloging tools.
  - `video.nfo`: Kodi / Jellyfin / Emby compatible movie & home video metadata.
  - `video.xmp`: Standard Adobe XMP sidecar for DigiKam, Darktable, and Adobe Bridge.
  - `video.mp4.edl`: Edit Decision List timeline markers for DaVinci Resolve.
- **🏷️ Safe Renaming with 1-Click Rollback**:
  - AI proposes chronological, highly descriptive filenames (e.g., `20150522_Kids_Swimming_Lake_Tahoe.mp4`).
  - Sidecars are automatically renamed alongside the video.
  - Every rename is recorded in an undo journal for instant 1-click reversal.
- **🛡️ Container Tagging with Integrity Verification**:
  - Safely write title, description, and keywords directly into MP4/MOV containers via FFmpeg stream-copy (no quality loss).
  - Verifies duration and audio/video stream integrity before finalizing, with automatic `.bak` safety backups.
- **⚙️ Machine-Readable Configuration**:
  - Export and import your entire setup as a portable JSON configuration file.

---

## 🚀 Deployment Options

### Option 1: Docker / Docker Compose (Recommended for Servers & NAS)

The included Docker configuration runs out of the box with FFmpeg pre-installed and volume mappings for persistent configuration and host video storage.

#### 1. Clone the repository
```bash
git clone https://github.com/benhayashi/cinetag.git
cd cinetag
```

#### 2. Configure media paths
Copy the sample environment file or set `MEDIA_DIR`:
```bash
export MEDIA_DIR="/path/to/your/home/videos"
```

#### 3. Start the container
```bash
docker compose up -d
```

- Open **`http://localhost:5555`** (or `http://your-server-ip:5555`).
- Video files located in your host media folder will be accessible inside the container at `/media`.
- Application configuration, logs, and face databases persist in `./data`.
- If your Ollama or LM Studio instance is running on the host machine, point the API URL in Settings to `http://host.docker.internal:11434`.

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

#### 2. How to Update on Ubuntu
Whenever a new version is released, update with a single command:
```bash
./update.sh
```
`update.sh` pulls the latest code from GitHub, applies any new dependency requirements to `.venv`, and preserves all your settings and databases.

---

### Option 3: Windows 10 / 11 (Native)

#### Prerequisites
1. **Python 3.10+**: Download from [python.org](https://www.python.org/downloads/) (make sure to check **"Add Python to PATH"** during installation).
2. **Git for Windows**: Download from [git-scm.com](https://git-scm.com/).
3. **FFmpeg**: Install quickly using Windows Package Manager:
   ```powershell
   winget install Gyan.FFmpeg
   ```
   *(Or place `ffmpeg.exe` and `ffprobe.exe` directly inside the `bin/` folder of this project).*

#### 1. Launch
Simply double-click **`run.bat`** (or open Command Prompt / PowerShell in the folder and run `run.bat`).
The script automatically sets up the `.venv` virtual environment, installs dependencies, and opens the application.

#### 2. How to Update on Windows
Simply double-click **`update.bat`**.
The script runs `git pull`, updates `.venv` packages, and notifies you when the update is complete.

---

### Option 4: macOS (Native)

#### Prerequisites
Install FFmpeg using [Homebrew](https://brew.sh/):
```bash
brew install ffmpeg python git
```

#### Launch & Update
- **Launch**: `./run.sh`
- **Update**: `./update.sh`

---

## 🤖 Configuring AI Providers

### Vision Models (Ollama or LM Studio)
1. Install [Ollama](https://ollama.com/) on your workstation or GPU server:
   ```bash
   ollama pull qwen2.5vl
   # or: ollama pull llama3.2-vision
   ```
2. In the CineTag dashboard, navigate to **Settings ⚙️** -> **AI Provider**.
3. Set your Ollama server URL (e.g., `http://localhost:11434` or `http://192.168.1.100:11434`).
4. Click **Test & Refresh Models** and select your model.

### Speech-to-Text (Whisper)
- **Built-in Faster-Whisper**: Runs locally on CPU or GPU. Select model sizes (`tiny`, `base`, `small`, `medium`, `large-v3`).
- **Remote Whisper API (TrueNAS SCALE / Docker / Unraid)**:
  - If running a Whisper container (like `hwds12/whisper-server`, `speaches`, or an OpenAI-compatible Whisper endpoint):
  - In **Settings ⚙️**, switch Whisper Provider to **Remote Whisper API**.
  - Enter your server address (e.g., `http://192.168.1.50:9000/v1`), model name, and optional API key.
  - Click **Test Connection** to verify connectivity before saving.

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
