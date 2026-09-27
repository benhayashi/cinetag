import os
import tempfile
from pathlib import Path
from src.core.paths import get_base_data_dir, get_cache_dir, is_portable_mode
from src.core.config import AppConfig, load_config, save_config

def test_config_defaults():
    cfg = AppConfig()
    assert cfg.vision_provider == "ollama"
    assert cfg.ollama_model == "llama3.2-vision"
    assert cfg.port == 5555
    assert cfg.transcribe_audio is True

def test_config_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    
    cfg = load_config()
    cfg.ollama_model = "qwen2.5vl"
    cfg.port = 8888
    save_config(cfg)

    loaded = load_config()
    assert loaded.ollama_model == "qwen2.5vl"
    assert loaded.port == 8888

def test_portable_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTABLE", "1")
    monkeypatch.delenv("VIDEO_DESCRIBER_DATA_DIR", raising=False)
    assert is_portable_mode() is True
