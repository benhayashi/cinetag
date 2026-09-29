import json
import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from src.core.config import AppConfig, load_config, save_config
from src.ai.ollama_provider import OllamaVisionProvider
from src.ai.base import FrameItem
from src.server.app import app

def test_ollama_num_ctx_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    cfg = AppConfig()
    assert cfg.ollama_num_ctx == 16384

    cfg.ollama_num_ctx = 32768
    save_config(cfg)

    loaded = load_config()
    assert loaded.ollama_num_ctx == 32768


def test_ollama_provider_passes_num_ctx_in_payload():
    provider = OllamaVisionProvider(base_url="http://localhost:11434", default_num_ctx=16384)

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "message": {
                "content": '{"title": "Test Title", "summary": "Test Summary", "events": [], "tags": [], "people_or_subjects": [], "animals_or_pets": [], "objects": [], "suggested_filename": "test"}'
            }
        }
        mock_instance.post.return_value = mock_res

        provider.describe_video(
            frames=[],
            num_ctx=16384
        )

        assert mock_instance.post.called
        call_kwargs = mock_instance.post.call_args[1]
        payload = call_kwargs["json"]
        assert "options" in payload
        assert payload["options"]["num_ctx"] == 16384
        assert payload["options"]["temperature"] == 0.2


def test_ollama_provider_auto_scales_on_large_prompt(tmp_path):
    frames = []
    for i in range(5):
        frame_file = tmp_path / f"frame_{i}.jpg"
        frame_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        frames.append(FrameItem(path=str(frame_file), timestamp_seconds=float(i), timecode=f"00:00:0{i}"))

    provider = OllamaVisionProvider(base_url="http://localhost:11434", default_num_ctx=4096)

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "message": {
                "content": '{"title": "Test Title", "summary": "Test Summary", "events": [], "tags": [], "people_or_subjects": [], "animals_or_pets": [], "objects": [], "suggested_filename": "test"}'
            }
        }
        mock_instance.post.return_value = mock_res

        # 5 frames * 1250 = 6250 tokens > 4096 configured context
        provider.describe_video(
            frames=frames,
            num_ctx=4096
        )

        call_kwargs = mock_instance.post.call_args[1]
        payload = call_kwargs["json"]
        # Must have scaled up beyond 4096
        assert payload["options"]["num_ctx"] > 4096


def test_ollama_provider_retries_and_self_heals_on_400_context_error():
    provider = OllamaVisionProvider(base_url="http://localhost:11434", default_num_ctx=4096)

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        # First response: 400 Bad Request matching user's exact Ollama error
        res_error = MagicMock()
        res_error.status_code = 400
        res_error.text = '{"error": "request (4188 tokens) exceeds the available context size (4096 tokens), try increasing it"}'

        # Second response: 200 OK after auto-adjusting num_ctx
        res_success = MagicMock()
        res_success.status_code = 200
        res_success.json.return_value = {
            "message": {
                "content": '{"title": "Healed Title", "summary": "Healed Summary", "events": [], "tags": [], "people_or_subjects": [], "animals_or_pets": [], "objects": [], "suggested_filename": "healed"}'
            }
        }

        mock_instance.post.side_effect = [res_error, res_success]

        result = provider.describe_video(
            frames=[],
            num_ctx=4096
        )

        assert mock_instance.post.call_count == 2
        # First call was 4096
        first_payload = mock_instance.post.call_args_list[0][1]["json"]
        assert first_payload["options"]["num_ctx"] == 4096

        # Second call auto-scaled to >= 8192
        second_payload = mock_instance.post.call_args_list[1][1]["json"]
        assert second_payload["options"]["num_ctx"] >= 8192
        assert result.title == "Healed Title"


def test_api_config_endpoint_ollama_num_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    client = TestClient(app)

    # Verify default GET
    get_res = client.get("/api/config")
    assert get_res.status_code == 200
    assert get_res.json()["ollama_num_ctx"] == 16384

    # Update via POST
    post_res = client.post("/api/config", json={"ollama_num_ctx": 32768})
    assert post_res.status_code == 200
    assert post_res.json()["config"]["ollama_num_ctx"] == 32768

    # Verify updated GET
    get_res2 = client.get("/api/config")
    assert get_res2.json()["ollama_num_ctx"] == 32768
