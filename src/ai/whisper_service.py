import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

from src.core.paths import get_models_dir

logger = logging.getLogger(__name__)

def normalize_whisper_urls(url: str, task: str = "transcribe") -> tuple[str, str]:
    """
    Returns (transcription_url, base_url).
    Handles root addresses, ports, /v1 paths, and full transcription/translation endpoints.
    Examples:
      'http://192.168.1.100:9000' -> ('http://192.168.1.100:9000/v1/audio/transcriptions', 'http://192.168.1.100:9000')
      'http://192.168.1.100:9000' with task='translate' -> ('http://192.168.1.100:9000/v1/audio/translations', 'http://192.168.1.100:9000')
      'http://nas-server:9000/v1' -> ('http://nas-server:9000/v1/audio/transcriptions', 'http://nas-server:9000')
    """
    if not url:
        return "", ""
    clean = url.strip().rstrip("/")
    endpoint = "translations" if task == "translate" else "transcriptions"
    if clean.endswith("/audio/transcriptions") or clean.endswith("/audio/translations"):
        base_endpoint = clean.rsplit("/audio/", 1)[0]
        transcribe_url = f"{base_endpoint}/audio/{endpoint}"
        base_url = clean.split("/v1")[0] if "/v1" in clean else clean.rsplit("/", 1)[0]
    elif clean.endswith("/transcriptions") or clean.endswith("/translations"):
        base_endpoint = clean.rsplit("/", 1)[0]
        transcribe_url = f"{base_endpoint}/{endpoint}"
        base_url = clean.split("/v1")[0] if "/v1" in clean else clean.rsplit("/", 1)[0]
    elif clean.endswith("/inference"):
        transcribe_url = clean
        base_url = clean.split("/v1")[0] if "/v1" in clean else clean.rsplit("/", 1)[0]
    elif clean.endswith("/v1"):
        transcribe_url = f"{clean}/audio/{endpoint}"
        base_url = clean[:-3]
    else:
        transcribe_url = f"{clean}/v1/audio/{endpoint}"
        base_url = clean
    return transcribe_url, base_url

def normalize_whisper_model_name(name: Optional[str]) -> str:
    """Normalize model identifiers like 'v3', 'large_v3' to official 'large-v3'."""
    n = (name or "base").strip().lower()
    if n in ("v3", "large_v3", "large-3"):
        return "large-v3"
    if n in ("v2", "large_v2", "large-2"):
        return "large-v2"
    if n in ("v1", "large_v1", "large-1"):
        return "large-v1"
    if n in ("turbo", "large-turbo", "large_turbo"):
        return "large-v3-turbo"
    return n

def patch_pyav_metadata_errors_if_needed():
    """
    PyAV removed the 'metadata_errors' parameter in recent releases (14+),
    causing faster-whisper's decode_audio to crash with:
    'open() got an unexpected keyword argument metadata_errors'.
    This patch wraps av.open so that if metadata_errors is rejected, it retries without it.
    """
    try:
        import av
        orig_av_open = av.open
        if getattr(orig_av_open, "_is_patched_for_metadata_errors", False):
            return

        def safe_av_open(*args, **kwargs):
            try:
                return orig_av_open(*args, **kwargs)
            except TypeError as te:
                if "metadata_errors" in str(te) and "metadata_errors" in kwargs:
                    kwargs.pop("metadata_errors", None)
                    return orig_av_open(*args, **kwargs)
                raise

        safe_av_open._is_patched_for_metadata_errors = True
        av.open = safe_av_open
        logger.debug("Successfully patched PyAV av.open for compatibility.")
    except Exception as e:
        logger.debug(f"PyAV patch skipped or failed: {e}")

# Run patch on module import
patch_pyav_metadata_errors_if_needed()

_WINDOWS_DLL_HANDLES = []

def configure_windows_cuda_dll_paths(log_callback=None):
    """
    On Windows with Python 3.8+, Windows DLL search path no longer checks PATH or site-packages by default.
    faster-whisper (ctranslate2) requires CUDA 12 DLLs: cublas64_12.dll, cublasLt64_12.dll, cudnn64_9.dll.
    Locate and register all directories containing NVIDIA CUDA DLLs via os.add_dll_directory() and PATH.
    """
    import sys
    if sys.platform != "win32":
        return

    import os
    from pathlib import Path
    global _WINDOWS_DLL_HANDLES

    candidate_dirs = set()

    # 1. Search site-packages for nvidia packages and torch
    for p in list(sys.path):
        p_path = Path(p)
        if not p_path.is_dir():
            continue
        nvidia_root = p_path / "nvidia"
        if nvidia_root.is_dir():
            try:
                for sub in nvidia_root.iterdir():
                    b_dir = sub / "bin"
                    if b_dir.is_dir():
                        candidate_dirs.add(b_dir.resolve())
                    l_dir = sub / "lib"
                    if l_dir.is_dir():
                        candidate_dirs.add(l_dir.resolve())
            except Exception:
                pass

        torch_lib = p_path / "torch" / "lib"
        if torch_lib.is_dir():
            candidate_dirs.add(torch_lib.resolve())

    # 2. Search CUDA_PATH environment variables
    for env_var in list(os.environ.keys()):
        if env_var.startswith("CUDA_PATH"):
            val = os.environ.get(env_var)
            if val:
                c_bin = Path(val) / "bin"
                if c_bin.is_dir():
                    candidate_dirs.add(c_bin.resolve())

    # 3. Search standard Program Files NVIDIA locations
    for pf_env in ("ProgramFiles", "ProgramFiles(x86)"):
        pf = os.environ.get(pf_env)
        if pf:
            cuda_dir = Path(pf) / "NVIDIA GPU Computing Toolkit" / "CUDA"
            if cuda_dir.is_dir():
                try:
                    for v_dir in cuda_dir.iterdir():
                        v_bin = v_dir / "bin"
                        if v_bin.is_dir():
                            candidate_dirs.add(v_bin.resolve())
                except Exception:
                    pass

    # 4. Search entries currently on PATH
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            e_path = Path(entry)
            if e_path.is_dir() and any(k in entry.lower() for k in ("cuda", "nvidia", "cublas", "cudnn", "torch")):
                try:
                    candidate_dirs.add(e_path.resolve())
                except Exception:
                    pass

    registered_count = 0
    for d in candidate_dirs:
        try:
            handle = os.add_dll_directory(str(d))
            _WINDOWS_DLL_HANDLES.append(handle)
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            registered_count += 1
        except Exception:
            pass

    if registered_count > 0 and log_callback:
        log_callback(f"[Whisper] Registered {registered_count} Windows CUDA DLL directory path(s) into process.")

def check_windows_cublas_loaded() -> bool:
    """Check if cublas64_12.dll is discoverable and loadable."""
    import sys
    if sys.platform != "win32":
        return True
    import ctypes
    for name in ("cublas64_12.dll", "cublasLt64_12.dll"):
        try:
            ctypes.CDLL(name)
            return True
        except Exception:
            pass
    return False

def ensure_windows_cuda_libs(log_callback=None) -> bool:
    """
    On Windows, ensure CUDA 12 cublas and cudnn DLLs are present and registered.
    If missing, attempts automatic one-time pip installation of nvidia-cublas-cu12 and nvidia-cudnn-cu12.
    """
    import sys
    if sys.platform != "win32":
        return True

    configure_windows_cuda_dll_paths(log_callback=log_callback)
    if check_windows_cublas_loaded():
        return True

    # Missing cublas64_12.dll: attempt automatic pip installation into current environment
    if log_callback:
        log_callback("[Whisper] CUDA 12 runtime (cublas64_12.dll) not found for faster-whisper. Installing nvidia-cublas-cu12 and nvidia-cudnn-cu12 for GPU acceleration...")
    logger.info("Attempting automatic installation of nvidia-cublas-cu12 and nvidia-cudnn-cu12...")

    import subprocess
    try:
        cmd = [sys.executable, "-m", "pip", "install", "nvidia-cublas-cu12", "nvidia-cudnn-cu12"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode == 0:
            if log_callback:
                log_callback("✅ Successfully installed nvidia-cublas-cu12 and nvidia-cudnn-cu12! Configuring DLL paths...")
            configure_windows_cuda_dll_paths(log_callback=log_callback)
            return check_windows_cublas_loaded()
        else:
            err = (proc.stderr or proc.stdout or "")[-300:]
            if log_callback:
                log_callback(f"⚠️ Automatic CUDA library installation returned: {err}", level="warning")
            return False
    except Exception as e:
        if log_callback:
            log_callback(f"⚠️ Failed to auto-install CUDA libraries: {e}", level="warning")
        return False

# Register Windows DLL paths on import
configure_windows_cuda_dll_paths()

def resolve_whisper_device_and_compute(requested_device: str = "auto", requested_compute: str = "auto") -> tuple[str, str]:
    """Determine the optimal execution device and quantization precision."""
    dev = (requested_device or "auto").strip().lower()
    comp = (requested_compute or "auto").strip().lower()

    has_cuda = False
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except Exception:
            has_cuda = False

    if dev == "cuda" or (dev == "auto" and has_cuda):
        actual_device = "cuda"
        actual_compute = "float16" if comp == "auto" else comp
    else:
        actual_device = "cpu"
        actual_compute = "int8" if comp == "auto" else comp

    return actual_device, actual_compute

class WhisperTranscriptionService:
    """Modular speech-to-text service supporting faster-whisper, standard whisper, and remote endpoints."""

    def __init__(
        self,
        backend: str = "faster-whisper",
        model_name: str = "base",
        device: str = "auto",
        device_index: int = 0,
        compute_type: str = "auto",
        remote_url: Optional[str] = None,
        language: Optional[str] = None,
        download_root: Optional[str] = None,
        api_key: Optional[str] = None,
        task: str = "transcribe",
        translate_to_english: bool = False
    ):
        self.backend = backend
        self.model_name = normalize_whisper_model_name(model_name)
        self.device = (device or "auto").strip().lower()
        self.device_index = int(device_index or 0)
        self.compute_type = (compute_type or "auto").strip().lower()
        self.remote_url = remote_url
        self.language = (language.strip() if language and language.strip() else None)
        self.download_root = download_root or str(get_models_dir())
        self.api_key = api_key
        self.task = "translate" if (translate_to_english or (task or "").strip().lower() == "translate") else "transcribe"
        self.translate_to_english = (self.task == "translate")
        self._model_instance = None

    def is_available(self) -> Dict[str, Any]:
        """Check which Whisper implementations and hardware acceleration devices are available."""
        has_faster_whisper = False
        has_openai_whisper = False
        has_cuda = False
        cuda_count = 0
        cuda_device_name = None
        cuda_devices = []
        supported_compute_types_cpu = []
        supported_compute_types_cuda = []

        try:
            import faster_whisper # type: ignore
            has_faster_whisper = True
        except ImportError:
            pass

        try:
            import whisper # type: ignore
            has_openai_whisper = True
        except ImportError:
            pass

        try:
            import ctranslate2
            cuda_count = ctranslate2.get_cuda_device_count()
            has_cuda = cuda_count > 0
            try:
                supported_compute_types_cpu = sorted(list(ctranslate2.get_supported_compute_types("cpu")))
            except Exception:
                supported_compute_types_cpu = ["int8", "float32"]
            if has_cuda:
                try:
                    supported_compute_types_cuda = sorted(list(ctranslate2.get_supported_compute_types("cuda")))
                except Exception:
                    supported_compute_types_cuda = ["float16", "int8"]
        except Exception:
            pass

        try:
            import torch
            if torch.cuda.is_available():
                has_cuda = True
                cuda_count = max(cuda_count, torch.cuda.device_count())
                for i in range(torch.cuda.device_count()):
                    dev_name = torch.cuda.get_device_name(i)
                    cuda_devices.append({"index": i, "name": dev_name})
                if cuda_devices:
                    cuda_device_name = ", ".join(f"[{d['index']}] {d['name']}" for d in cuda_devices)
        except Exception:
            pass

        models_dir = Path(self.download_root)
        downloaded = []
        if models_dir.exists():
            for d in models_dir.iterdir():
                if d.is_dir():
                    name = d.name
                    if "models--" in name:
                        name = name.split("--")[-1].replace("faster-whisper-", "")
                    downloaded.append(name)

        return {
            "faster_whisper": has_faster_whisper,
            "openai_whisper": has_openai_whisper,
            "cuda_available": has_cuda,
            "cuda_device_count": cuda_count,
            "cuda_device_name": cuda_device_name,
            "cuda_devices": cuda_devices,
            "supported_compute_types_cpu": supported_compute_types_cpu,
            "supported_compute_types_cuda": supported_compute_types_cuda,
            "remote": bool(self.remote_url),
            "remote_url": self.remote_url,
            "has_api_key": bool(self.api_key),
            "preferred_backend": self.backend,
            "task": self.task,
            "translate_to_english": self.translate_to_english,
            "language": self.language,
            "models_dir": str(models_dir),
            "downloaded_models": sorted(list(set(downloaded)))
        }


    def transcribe(self, audio_path: Path, log_callback=None) -> Optional[str]:
        """Transcribe audio file to text. Returns transcript or None."""
        res = self.transcribe_detailed(audio_path, log_callback=log_callback)
        return res.get("text") if res else None

    def transcribe_detailed(self, audio_path: Path, log_callback=None) -> Dict[str, Any]:
        """Transcribe audio file to text with timestamped segments for SRT export."""
        if not audio_path or not audio_path.exists() or audio_path.stat().st_size == 0:
            return {"text": None, "segments": []}

        if self.backend == "faster-whisper":
            return self._transcribe_faster_whisper(audio_path, log_callback=log_callback)
        elif self.backend == "openai-whisper":
            return self._transcribe_openai_whisper(audio_path, log_callback=log_callback)
        elif self.backend == "remote":
            return self._transcribe_remote(audio_path, log_callback=log_callback)
        else:
            avail = self.is_available()
            if avail["faster_whisper"]:
                return self._transcribe_faster_whisper(audio_path, log_callback=log_callback)
            elif avail["openai_whisper"]:
                return self._transcribe_openai_whisper(audio_path, log_callback=log_callback)
            elif self.remote_url:
                return self._transcribe_remote(audio_path, log_callback=log_callback)
            else:
                if log_callback:
                    log_callback("⚠️ No Whisper backend installed in Python environment.", "warning")
                logger.info("No Whisper backend installed. Skipping speech transcription.")
                return {"text": None, "segments": []}

    def _transcribe_faster_whisper(self, audio_path: Path, log_callback=None) -> Dict[str, Any]:
        def log(msg: str, level: str = "info"):
            if log_callback:
                try:
                    log_callback(msg, level)
                except Exception:
                    pass
            if level == "warning":
                logger.warning(msg)
            elif level == "error":
                logger.error(msg)
            else:
                logger.info(msg)

        try:
            from faster_whisper import WhisperModel # type: ignore
        except ImportError:
            log("⚠️ faster-whisper package not installed. Skipping speech transcription.", level="warning")
            return {"text": None, "segments": [], "error": "faster-whisper package not installed"}

        patch_pyav_metadata_errors_if_needed()
        import sys
        if sys.platform == "win32":
            configure_windows_cuda_dll_paths(log_callback=log)

        target_device, target_compute = resolve_whisper_device_and_compute(self.device, self.compute_type)
        if target_device == "cuda" and sys.platform == "win32":
            ensure_windows_cuda_libs(log_callback=log)

        def run_inference(dev: str, comp: str) -> tuple[str, list]:
            patch_pyav_metadata_errors_if_needed()
            kwargs = {
                "device": dev,
                "compute_type": comp,
                "download_root": self.download_root
            }
            if dev == "cuda" and self.device_index >= 0:
                kwargs["device_index"] = self.device_index
                log(f"[Whisper] Initializing model '{self.model_name}' on {dev.upper()} [GPU {self.device_index}] ({comp})...")
            else:
                log(f"[Whisper] Initializing model '{self.model_name}' on {dev.upper()} ({comp})...")

            model = WhisperModel(self.model_name, **kwargs)
            action_desc = "audio transcription & translation to English" if self.task == "translate" else "audio transcription"
            log(f"[Whisper] Starting {action_desc} on {dev.upper()}...")
            segments, info = model.transcribe(
                str(audio_path),
                language=self.language,
                task=self.task,
                beam_size=5
            )
            seg_list = []
            text_parts = []
            for segment in segments:
                t = segment.text.strip()
                if t:
                    text_parts.append(t)
                    seg_list.append({
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "text": t
                    })
            full_text = " ".join(text_parts).strip()
            detected_lang = getattr(info, "language", None) or "auto"
            lang_str = f"detected language: {detected_lang}" + (" (translated to en)" if self.task == "translate" and detected_lang != "en" else "")
            done_desc = "Transcription & translation to English" if self.task == "translate" else "Transcription"
            log(f"[Whisper] {done_desc} completed on {dev.upper()}: {len(seg_list)} segments detected (audio duration: {info.duration:.1f}s, {lang_str}).")
            return full_text, seg_list

        try:
            full_text, seg_list = run_inference(target_device, target_compute)
            return {"text": full_text, "segments": seg_list}
        except Exception as primary_err:
            log(f"⚠️ Whisper error on {target_device.upper()} ({target_compute}): {primary_err}", level="warning")
            if target_device == "cuda":
                log("⚡ Automatically falling back to CPU execution (int8) for guaranteed compatibility...", level="info")
                try:
                    full_text, seg_list = run_inference("cpu", "int8")
                    return {"text": full_text, "segments": seg_list}
                except Exception as cpu_err:
                    log(f"❌ CPU fallback transcription also failed: {cpu_err}", level="error")
                    return {"text": None, "segments": [], "error": f"GPU: {primary_err} | CPU: {cpu_err}"}
            else:
                return {"text": None, "segments": [], "error": str(primary_err)}

    def _transcribe_openai_whisper(self, audio_path: Path, log_callback=None) -> Dict[str, Any]:
        try:
            import whisper # type: ignore
            if self._model_instance is None:
                if log_callback:
                    log_callback(f"[Whisper] Loading openai-whisper model '{self.model_name}'...")
                self._model_instance = whisper.load_model(self.model_name)

            if log_callback:
                action_desc = "Transcribing audio and translating to English" if self.task == "translate" else "Transcribing audio"
                log_callback(f"[Whisper] {action_desc} with openai-whisper...")
            result = self._model_instance.transcribe(str(audio_path), language=self.language, task=self.task)

            raw_text = result.get("text", "").strip()
            seg_list = []
            for s in result.get("segments", []):
                t = s.get("text", "").strip()
                if t:
                    seg_list.append({
                        "start": float(s.get("start", 0.0)),
                        "end": float(s.get("end", 0.0)),
                        "text": t
                    })
            return {"text": raw_text, "segments": seg_list}
        except ImportError:
            logger.warning("whisper package not installed.")
            return {"text": None, "segments": []}
        except Exception as e:
            logger.error(f"openai-whisper transcription failed: {e}")
            return {"text": None, "segments": []}

    def _transcribe_remote(self, audio_path: Path, log_callback=None) -> Dict[str, Any]:
        def log(msg: str, level: str = "info"):
            if log_callback:
                try:
                    log_callback(msg, level)
                except Exception:
                    pass
            if level == "error":
                logger.error(msg)
            elif level == "warning":
                logger.warning(msg)
            else:
                logger.info(msg)

        if not self.remote_url:
            log("⚠️ Remote Whisper URL is not configured.", level="warning")
            return {"text": None, "segments": [], "error": "Remote Whisper URL not configured"}

        try:
            import httpx
            transcribe_url, base_url = normalize_whisper_urls(self.remote_url, task=self.task)
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            if not audio_path.exists() or audio_path.stat().st_size <= 44:
                err_msg = f"Audio file is empty ({audio_path.stat().st_size if audio_path.exists() else 0} bytes)"
                log(f"⚠️ {err_msg}", level="warning")
                return {"text": None, "segments": [], "error": err_msg}

            audio_bytes = audio_path.read_bytes()
            suffix = audio_path.suffix.lower()
            mime = "audio/wav" if suffix in (".wav", "") else f"audio/{suffix.lstrip('.')}"
            filename = audio_path.name

            task_info = f", task: '{self.task}'" if self.task == "translate" else ""
            log(f"[Remote Whisper] Connecting to {self.remote_url} (model: '{self.model_name}'{task_info}, audio size: {len(audio_bytes) / 1024:.1f} KB)...")

            # Estimate duration in seconds from audio size (16kHz 16-bit mono PCM is ~32 KB/sec)
            est_audio_seconds = (len(audio_bytes) / 1024.0) / 32.0
            # Allow at least 600s (10 min), and scale generously with audio length (est_audio_seconds * 1.5 + 300s buffer, up to 3600s / 1 hr)
            request_timeout = max(600.0, min(3600.0, est_audio_seconds * 1.5 + 300.0))

            with httpx.Client(timeout=request_timeout) as client:
                res = None
                last_err = None

                # Strategy 1: OpenAI-compatible /v1/audio/transcriptions or /v1/audio/translations (Speaches, faster-whisper-server, LocalAI, vLLM)
                data_payload = {
                    "model": self.model_name or "base",
                    "response_format": "verbose_json"
                }
                if self.language:
                    data_payload["language"] = self.language
                if self.task == "translate":
                    data_payload["task"] = "translate"

                try:
                    files = {"file": (filename, audio_bytes, mime)}
                    first_res = client.post(transcribe_url, files=files, data=data_payload, headers=headers)
                    if first_res.status_code in (400, 422) and "response_format" in data_payload:
                        # Fallback to plain json format if verbose_json rejected
                        data_payload.pop("response_format", None)
                        files = {"file": (filename, audio_bytes, mime)}
                        first_res = client.post(transcribe_url, files=files, data=data_payload, headers=headers)
                    if first_res.status_code == 404 and self.task == "translate" and "/translations" in transcribe_url:
                        # Some servers implement /transcriptions with task="translate" rather than /translations
                        alt_url = transcribe_url.replace("/translations", "/transcriptions")
                        files = {"file": (filename, audio_bytes, mime)}
                        first_res = client.post(alt_url, files=files, data=data_payload, headers=headers)
                    first_res.raise_for_status()
                    res = first_res
                except Exception as e1:
                    last_err = e1

                # Strategy 2: If /v1/audio/transcriptions returned 404 or failed, try ASR WebService (/asr)
                # (Standard on Docker / homelab NAS containers like ahmetoner/whisper-asr-webservice)
                if res is None:
                    asr_url = f"{base_url}/asr"
                    asr_params = {"task": self.task, "output": "json"}
                    if self.language:
                        asr_params["language"] = self.language
                    try:
                        files_asr = {"audio_file": (filename, audio_bytes, mime)}
                        asr_res = client.post(asr_url, files=files_asr, params=asr_params, headers=headers)
                        if asr_res.status_code == 200:
                            res = asr_res
                        elif asr_res.status_code in (400, 422):
                            files_asr_alt = {"file": (filename, audio_bytes, mime)}
                            asr_res2 = client.post(asr_url, files=files_asr_alt, params=asr_params, headers=headers)
                            if asr_res2.status_code == 200:
                                res = asr_res2
                    except Exception:
                        pass

                # Strategy 3: Check /v1/models if error was model mismatch (e.g. Systran/faster-whisper-large-v3)
                if res is None and last_err is not None:
                    try:
                        m_res = client.get(f"{base_url}/v1/models", headers=headers, timeout=5.0)
                        if m_res.status_code == 200:
                            m_data = m_res.json()
                            avail_models = []
                            if isinstance(m_data, dict) and "data" in m_data:
                                avail_models = [m.get("id") for m in m_data["data"] if isinstance(m, dict) and "id" in m]
                            elif isinstance(m_data, dict) and "models" in m_data:
                                avail_models = [m.get("id") if isinstance(m, dict) else str(m) for m in m_data["models"]]

                            if avail_models:
                                matched_model = None
                                for am in avail_models:
                                    if self.model_name and self.model_name in am.lower():
                                        matched_model = am
                                        break
                                if not matched_model and len(avail_models) == 1:
                                    matched_model = avail_models[0]

                                if matched_model and matched_model != self.model_name:
                                    log(f"[Remote Whisper] Server uses model identifier '{matched_model}'. Retrying...")
                                    files = {"file": (filename, audio_bytes, mime)}
                                    retry_data = {"model": matched_model}
                                    if self.language:
                                        retry_data["language"] = self.language
                                    if self.task == "translate":
                                        retry_data["task"] = "translate"
                                    retry_res = client.post(transcribe_url, files=files, data=retry_data, headers=headers)
                                    if retry_res.status_code == 200:
                                        res = retry_res
                    except Exception:
                        pass

                if res is None:
                    raise last_err or RuntimeError(f"Could not connect to Remote Whisper at {self.remote_url}")

                raw_text = ""
                seg_list = []
                content_type = res.headers.get("content-type", "")

                if "application/json" in content_type or res.text.strip().startswith(("{", "[")):
                    jdata = res.json()
                    if isinstance(jdata, dict):
                        raw_text = jdata.get("text", "") or jdata.get("transcription", "") or ""
                        raw_segments = jdata.get("segments", [])
                        if isinstance(raw_segments, list):
                            for s in raw_segments:
                                if isinstance(s, dict):
                                    stext = s.get("text", "").strip()
                                    if stext:
                                        seg_list.append({
                                            "start": float(s.get("start", 0.0)),
                                            "end": float(s.get("end", 0.0)),
                                            "text": stext
                                        })
                    elif isinstance(jdata, list):
                        for item in jdata:
                            if isinstance(item, dict):
                                stext = item.get("text", "").strip()
                                if stext:
                                    seg_list.append({
                                        "start": float(item.get("start", 0.0)),
                                        "end": float(item.get("end", 0.0)),
                                        "text": stext
                                    })
                        raw_text = " ".join(s["text"] for s in seg_list)
                    elif isinstance(jdata, str):
                        raw_text = jdata
                else:
                    raw_text = res.text.strip()

                final_text = raw_text.strip() if raw_text else None
                if final_text:
                    action_done = "Translation & transcription" if self.task == "translate" else "Transcription"
                    log(f"[Remote Whisper] {action_done} received successfully: {len(final_text)} chars, {len(seg_list)} segment(s).")
                else:
                    log(f"[Remote Whisper] Server returned response (HTTP {res.status_code}), but no dialogue text was found in the audio.", level="info")

                return {
                    "text": final_text,
                    "segments": seg_list
                }

        except Exception as e:
            err_msg = f"Remote whisper request to {self.remote_url} failed: {e}"
            log(f"⚠️ {err_msg}", level="warning")
            return {"text": None, "segments": [], "error": err_msg}
