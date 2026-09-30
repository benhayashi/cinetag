import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

from src.core.paths import get_models_dir

logger = logging.getLogger(__name__)

def normalize_whisper_urls(url: str) -> tuple[str, str]:
    """
    Returns (transcription_url, base_url).
    Handles root addresses, ports, /v1 paths, and full transcription endpoints.
    Examples:
      'http://192.168.1.100:9000' -> ('http://192.168.1.100:9000/v1/audio/transcriptions', 'http://192.168.1.100:9000')
      'http://truenas:9000/v1'   -> ('http://truenas:9000/v1/audio/transcriptions', 'http://truenas:9000')
      'http://host:9000/v1/audio/transcriptions' -> ('http://host:9000/v1/audio/transcriptions', 'http://host:9000')
    """
    if not url:
        return "", ""
    clean = url.strip().rstrip("/")
    if clean.endswith("/audio/transcriptions") or clean.endswith("/transcriptions") or clean.endswith("/inference"):
        transcribe_url = clean
        base_url = clean.split("/v1")[0] if "/v1" in clean else clean.rsplit("/", 1)[0]
    elif clean.endswith("/v1"):
        transcribe_url = f"{clean}/audio/transcriptions"
        base_url = clean[:-3]
    else:
        transcribe_url = f"{clean}/v1/audio/transcriptions"
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
        compute_type: str = "auto",
        remote_url: Optional[str] = None,
        language: Optional[str] = None,
        download_root: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        self.backend = backend
        self.model_name = normalize_whisper_model_name(model_name)
        self.device = (device or "auto").strip().lower()
        self.compute_type = (compute_type or "auto").strip().lower()
        self.remote_url = remote_url
        self.language = language
        self.download_root = download_root or str(get_models_dir())
        self.api_key = api_key
        self._model_instance = None

    def is_available(self) -> Dict[str, Any]:
        """Check which Whisper implementations and hardware acceleration devices are available."""
        has_faster_whisper = False
        has_openai_whisper = False
        has_cuda = False
        cuda_count = 0
        cuda_device_name = None
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
                try:
                    cuda_device_name = torch.cuda.get_device_name(0)
                except Exception:
                    pass
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
            "supported_compute_types_cpu": supported_compute_types_cpu,
            "supported_compute_types_cuda": supported_compute_types_cuda,
            "remote": bool(self.remote_url),
            "remote_url": self.remote_url,
            "has_api_key": bool(self.api_key),
            "preferred_backend": self.backend,
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
            return self._transcribe_remote(audio_path)
        else:
            avail = self.is_available()
            if avail["faster_whisper"]:
                return self._transcribe_faster_whisper(audio_path, log_callback=log_callback)
            elif avail["openai_whisper"]:
                return self._transcribe_openai_whisper(audio_path, log_callback=log_callback)
            elif self.remote_url:
                return self._transcribe_remote(audio_path)
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

        target_device, target_compute = resolve_whisper_device_and_compute(self.device, self.compute_type)

        def run_inference(dev: str, comp: str) -> tuple[str, list]:
            log(f"[Whisper] Initializing model '{self.model_name}' on {dev.upper()} ({comp})...")
            model = WhisperModel(
                self.model_name,
                device=dev,
                compute_type=comp,
                download_root=self.download_root
            )
            log(f"[Whisper] Starting audio transcription on {dev.upper()}...")
            segments, info = model.transcribe(
                str(audio_path),
                language=self.language,
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
            log(f"[Whisper] Transcription completed on {dev.upper()}: {len(seg_list)} segments detected (audio duration: {info.duration:.1f}s, language: {info.language}).")
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
                log_callback(f"[Whisper] Transcribing audio with openai-whisper...")
            result = self._model_instance.transcribe(str(audio_path), language=self.language)

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

    def _transcribe_remote(self, audio_path: Path) -> Dict[str, Any]:
        if not self.remote_url:
            return {"text": None, "segments": []}
        try:
            import httpx
            transcribe_url, _ = normalize_whisper_urls(self.remote_url)
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            suffix = audio_path.suffix.lower()
            mime = "audio/wav" if suffix in (".wav", "") else f"audio/{suffix.lstrip('.')}"

            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, mime)}
                data = {
                    "model": self.model_name or "base",
                    "response_format": "verbose_json"
                }
                if self.language:
                    data["language"] = self.language

                with httpx.Client(timeout=300.0) as client:
                    try:
                        res = client.post(transcribe_url, files=files, data=data, headers=headers)
                        res.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        # Fallback without verbose_json if remote server only accepts plain json
                        if e.response.status_code in (400, 422) and "response_format" in data:
                            f.seek(0)
                            data.pop("response_format", None)
                            res = client.post(transcribe_url, files=files, data=data, headers=headers)
                            res.raise_for_status()
                        else:
                            raise

                    jdata = res.json()
                    raw_text = jdata.get("text", "") or jdata.get("transcription", "")
                    
                    seg_list = []
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

                    return {
                        "text": raw_text.strip() if raw_text else None,
                        "segments": seg_list
                    }
        except Exception as e:
            logger.error(f"Remote whisper request to {self.remote_url} failed: {e}")
            return {"text": None, "segments": []}
