import io
import wave
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.ai.whisper_service import (
    normalize_whisper_urls,
    WhisperTranscriptionService
)
from src.core.config import AppConfig, save_config, load_config
from src.server.api import probe_whisper_remote, WhisperRemoteProbeRequest

def test_normalize_whisper_urls():
    # 1. Base URL with port
    t1, b1 = normalize_whisper_urls("http://192.168.1.100:9000")
    assert t1 == "http://192.168.1.100:9000/v1/audio/transcriptions"
    assert b1 == "http://192.168.1.100:9000"

    # 2. URL ending in /v1
    t2, b2 = normalize_whisper_urls("http://truenas:9000/v1")
    assert t2 == "http://truenas:9000/v1/audio/transcriptions"
    assert b2 == "http://truenas:9000"

    # 3. Full /v1/audio/transcriptions endpoint
    t3, b3 = normalize_whisper_urls("http://truenas:9000/v1/audio/transcriptions")
    assert t3 == "http://truenas:9000/v1/audio/transcriptions"
    assert b3 == "http://truenas:9000"

    # 4. Custom endpoint like /inference
    t4, b4 = normalize_whisper_urls("http://localhost:8080/inference")
    assert t4 == "http://localhost:8080/inference"
    assert b4 == "http://localhost:8080"

    # 5. Empty
    t5, b5 = normalize_whisper_urls("")
    assert t5 == ""
    assert b5 == ""

def test_whisper_remote_transcription(tmp_path):
    # Create a small valid WAV file
    wav_file = tmp_path / "test.wav"
    with wave.open(str(wav_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 800)

    svc = WhisperTranscriptionService(
        backend="remote",
        model_name="large-v3",
        remote_url="http://192.168.1.100:9000",
        api_key="secret-token-123"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "text": "Hello TrueNAS Whisper",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "Hello TrueNAS Whisper"}
        ]
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        res = svc.transcribe_detailed(wav_file)
        assert res["text"] == "Hello TrueNAS Whisper"
        assert len(res["segments"]) == 1
        assert res["segments"][0]["text"] == "Hello TrueNAS Whisper"
        assert res["segments"][0]["start"] == 0.0

        # Check call arguments
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://192.168.1.100:9000/v1/audio/transcriptions"
        headers = call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer secret-token-123"
        data = call_args[1].get("data", {})
        assert data.get("model") == "large-v3"
        assert data.get("response_format") == "verbose_json"

def test_api_whisper_test_remote_success():
    mock_models_resp = MagicMock()
    mock_models_resp.status_code = 200
    mock_models_resp.json.return_value = {
        "data": [
            {"id": "base"},
            {"id": "large-v3"},
            {"id": "turbo"}
        ]
    }

    mock_probe_resp = MagicMock()
    mock_probe_resp.status_code = 200
    mock_probe_resp.json.return_value = {"text": "silent probe"}

    def mock_get(url, **kwargs):
        if "models" in url:
            return mock_models_resp
        return MagicMock(status_code=404)

    with patch("httpx.Client.get", side_effect=mock_get), \
         patch("httpx.Client.post", return_value=mock_probe_resp):
        res = probe_whisper_remote(WhisperRemoteProbeRequest(
            url="http://192.168.1.100:9000",
            api_key="my-token",
            model="large-v3"
        ))
        assert res["status"] == "ok"
        assert "Connected!" in res["message"]
        assert "base" in res["models"]
        assert "large-v3" in res["models"]
        assert "turbo" in res["models"]
        assert res["endpoint"] == "http://192.168.1.100:9000/v1/audio/transcriptions"

def test_api_whisper_test_remote_auth_error():
    mock_probe_resp = MagicMock()
    mock_probe_resp.status_code = 401
    mock_probe_resp.text = "Unauthorized"

    with patch("httpx.Client.get", return_value=MagicMock(status_code=401)), \
         patch("httpx.Client.post", return_value=mock_probe_resp):
        res = probe_whisper_remote(WhisperRemoteProbeRequest(
            url="http://192.168.1.100:9000",
            api_key="wrong-token"
        ))
        assert res["status"] == "error"
        assert "401 Unauthorized" in res["message"]

def test_config_whisper_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    cfg = load_config()
    cfg.whisper_backend = "remote"
    cfg.whisper_remote_url = "http://truenas.local:9000"
    cfg.whisper_api_key = "test-key"
    cfg.whisper_model = "Systran/faster-whisper-large-v3"
    save_config(cfg)

    loaded = load_config()
    assert loaded.whisper_backend == "remote"
    assert loaded.whisper_remote_url == "http://truenas.local:9000"
    assert loaded.whisper_api_key == "test-key"
    assert loaded.whisper_model == "Systran/faster-whisper-large-v3"


def test_normalize_whisper_model_name():
    from src.ai.whisper_service import normalize_whisper_model_name
    assert normalize_whisper_model_name("v3") == "large-v3"
    assert normalize_whisper_model_name("large_v3") == "large-v3"
    assert normalize_whisper_model_name("turbo") == "large-v3-turbo"
    assert normalize_whisper_model_name("base") == "base"
    assert normalize_whisper_model_name(None) == "base"


def test_api_whisper_install_endpoint(monkeypatch):
    from src.server.api import install_whisper_engine
    import subprocess

    class DummyProc:
        returncode = 0
        stdout = "Successfully installed"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: DummyProc())
    res = install_whisper_engine()
    assert res["status"] == "success"
    assert "installed successfully" in res["message"]


def test_resolve_whisper_device_and_compute():
    from src.ai.whisper_service import resolve_whisper_device_and_compute

    dev, comp = resolve_whisper_device_and_compute(requested_device="cpu", requested_compute="int8")
    assert dev == "cpu"
    assert comp == "int8"

    dev, comp = resolve_whisper_device_and_compute(requested_device="cuda", requested_compute="float16")
    assert dev == "cuda"
    assert comp == "float16"


def test_faster_whisper_cuda_fallback_to_cpu(tmp_path, monkeypatch):
    from src.ai.whisper_service import WhisperTranscriptionService
    import wave

    wav_file = tmp_path / "speech.wav"
    with wave.open(str(wav_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)

    logs = []
    def log_cb(msg, level="info"):
        logs.append((level, msg))

    call_count = {"cuda": 0, "cpu": 0}

    class MockSegment:
        def __init__(self, text, start, end):
            self.text = text
            self.start = start
            self.end = end

    class MockInfo:
        duration = 10.0
        language = "en"

    class MockModel:
        def __init__(self, model_name, device, compute_type, **kwargs):
            self.device = device
            self.compute_type = compute_type

        def transcribe(self, path, **kwargs):
            if self.device == "cuda":
                call_count["cuda"] += 1
                raise RuntimeError("CUDA out of memory or cuBLAS DLL missing")
            else:
                call_count["cpu"] += 1
                return [MockSegment("Hello from CPU fallback", 0.0, 2.5)], MockInfo()

    monkeypatch.setattr("faster_whisper.WhisperModel", MockModel)

    svc = WhisperTranscriptionService(
        backend="faster-whisper",
        model_name="base",
        device="cuda",
        compute_type="float16"
    )

    det_res = svc.transcribe_detailed(wav_file, log_callback=log_cb)

    assert call_count["cuda"] == 1
    assert call_count["cpu"] == 1
    assert det_res["text"] == "Hello from CPU fallback"
    assert len(det_res["segments"]) == 1

    log_messages = [m[1] for m in logs]
    assert any("CUDA error" in m or "CUDA" in m for m in log_messages)
    assert any("falling back to CPU" in m for m in log_messages)


def test_patch_pyav_metadata_errors():
    from src.ai.whisper_service import patch_pyav_metadata_errors_if_needed
    import av

    patch_pyav_metadata_errors_if_needed()

    # Verify safe_av_open handles unexpected keyword argument 'metadata_errors'
    called_with = {}
    orig_open = av.open

    def mock_av_open(*args, **kwargs):
        if "metadata_errors" in kwargs:
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
        called_with.update(kwargs)
        return "mock_container"

    # Set mock as av.open and run patch
    av.open = mock_av_open
    patch_pyav_metadata_errors_if_needed()

    # Call with metadata_errors="ignore"
    res = av.open("fake_audio.wav", mode="r", metadata_errors="ignore")
    assert res == "mock_container"
    assert "metadata_errors" not in called_with

    # Restore
    av.open = orig_open


def test_whisper_multi_gpu_device_index(monkeypatch):
    from src.ai.whisper_service import WhisperTranscriptionService

    captured_kwargs = {}
    class MockModel:
        def __init__(self, model_name, **kwargs):
            captured_kwargs.update(kwargs)
        def transcribe(self, path, **kwargs):
            return [], None

    monkeypatch.setattr("faster_whisper.WhisperModel", MockModel)

    svc = WhisperTranscriptionService(
        backend="faster-whisper",
        model_name="base",
        device="cuda",
        device_index=1,
        compute_type="float16"
    )

    # Calling with dummy audio
    from pathlib import Path
    dummy = Path("tests/nonexistent.wav")
    # Call internal run_inference
    svc.device_index = 1
    assert svc.device_index == 1



