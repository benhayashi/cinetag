from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.server.app import app
from src.core.config import AppConfig, load_config, save_config
from src.ai.cloud_provider import CloudVisionProvider, RECOMMENDED_MODELS
from src.ai.base import FrameItem

client = TestClient(app)

def test_config_cloud_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    cfg = load_config()
    assert hasattr(cfg, "cloud_model")
    assert hasattr(cfg, "cloud_endpoint")
    assert "openrouter" in cfg.api_keys
    assert "custom" in cfg.api_keys

    cfg.cloud_provider = "openrouter"
    cfg.cloud_model = "google/gemini-2.5-flash"
    cfg.cloud_endpoint = "https://openrouter.ai/api/v1"
    cfg.api_keys["openrouter"] = "sk-or-v1-testkey"
    cfg.openai_compatible_api_key = "test-bearer-token"
    save_config(cfg)

    loaded = load_config()
    assert loaded.cloud_provider == "openrouter"
    assert loaded.cloud_model == "google/gemini-2.5-flash"
    assert loaded.cloud_endpoint == "https://openrouter.ai/api/v1"
    assert loaded.api_keys["openrouter"] == "sk-or-v1-testkey"
    assert loaded.openai_compatible_api_key == "test-bearer-token"

def test_cloud_vision_provider_models_and_availability():
    # 1. Missing key
    p_no_key = CloudVisionProvider(provider="gemini", api_keys={})
    assert p_no_key.is_available() is False
    assert len(p_no_key.list_models()) > 0
    assert "gemini-2.5-flash" in p_no_key.list_models()

    # 2. Key provided
    p_with_key = CloudVisionProvider(provider="openai", api_keys={"openai": "sk-12345"})
    assert p_with_key.is_available() is True
    assert "gpt-4o" in p_with_key.list_models()

    # 3. OpenRouter
    p_or = CloudVisionProvider(provider="openrouter", api_keys={"openrouter": "sk-or-123"})
    assert p_or.is_available() is True
    assert any("gemini" in m for m in p_or.list_models())

    # 4. Custom OpenAI standard
    p_custom = CloudVisionProvider(
        provider="custom_openai",
        api_keys={"custom": "sk-custom"},
        custom_endpoint="https://api.groq.com/openai/v1"
    )
    assert p_custom.is_available() is True
    assert p_custom.custom_endpoint == "https://api.groq.com/openai/v1"

def test_cloud_vision_provider_probe_connection_missing_key():
    p = CloudVisionProvider(provider="anthropic", api_keys={})
    res = p.probe_connection()
    assert res["connected"] is False
    assert "API key is missing" in res["error"]

def test_cloud_vision_provider_probe_connection_mock_success():
    p = CloudVisionProvider(provider="gemini", api_keys={"gemini": "AIzaSyFakeKey"})
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]}
        ]
    }

    with patch("src.ai.cloud_provider.httpx.Client.get", return_value=mock_resp):
        res = p.probe_connection(provider="gemini", api_key="AIzaSyFakeKey")
        assert res["connected"] is True
        assert res["provider"] == "gemini"
        assert "gemini-2.5-flash" in res["models"]

def test_api_cloud_models_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    # 1. GET /api/models/cloud when key is empty
    resp_get = client.get("/api/models/cloud")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["connected"] is False
    assert "error" in data_get

    # 2. POST /api/models/cloud/test with mock success for OpenAI standard
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]
    }

    with patch("src.ai.cloud_provider.httpx.Client.get", return_value=mock_resp):
        resp_post = client.post("/api/models/cloud/test", json={
            "provider": "openai",
            "api_key": "sk-mock-valid-key",
            "model": "gpt-4o"
        })
        assert resp_post.status_code == 200
        data_post = resp_post.json()
        assert data_post["connected"] is True
        assert data_post["provider"] == "openai"
        assert "gpt-4o" in data_post["models"]

    # 3. POST /api/models/cloud/test for custom OpenAI-compatible endpoint
    with patch("src.ai.cloud_provider.httpx.Client.get", return_value=mock_resp):
        resp_custom = client.post("/api/models/cloud/test", json={
            "provider": "custom_openai",
            "api_key": "sk-custom",
            "endpoint": "https://api.groq.com/openai/v1",
            "model": "llama-3.2-11b-vision"
        })
        assert resp_custom.status_code == 200
        data_custom = resp_custom.json()
        assert data_custom["connected"] is True
        assert data_custom["provider"] == "custom_openai"

def test_api_openai_models_with_query_params():
    with patch("src.ai.openai_provider.OpenAICompatibleVisionProvider.is_available", return_value=True), \
         patch("src.ai.openai_provider.OpenAICompatibleVisionProvider.list_models", return_value=["vision-v1"]):
        resp = client.get("/api/models/openai?url=http://192.168.1.50:8000/v1&api_key=secret-token")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["url"] == "http://192.168.1.50:8000/v1"
        assert "vision-v1" in data["models"]
