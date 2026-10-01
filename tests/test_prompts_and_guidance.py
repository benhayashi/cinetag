import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.ai.prompt import build_user_prompt, get_system_prompt, DEFAULT_SYSTEM_PROMPT
from src.core.config import AppConfig
from src.server.app import app
from src.server.queue_manager import QueueManager, TaskItem

client = TestClient(app)


def test_get_system_prompt():
    # When None or empty, returns DEFAULT_SYSTEM_PROMPT
    assert get_system_prompt(None) == DEFAULT_SYSTEM_PROMPT
    assert get_system_prompt("") == DEFAULT_SYSTEM_PROMPT
    assert get_system_prompt("   ") == DEFAULT_SYSTEM_PROMPT

    # When custom provided, returns the custom prompt
    custom = "You are an expert wildlife documentary analyzer."
    assert get_system_prompt(custom) == custom


def test_build_user_prompt_without_guidance():
    prompt = build_user_prompt(
        timestamps=["00:00", "00:15"],
        audio_transcript="Hello world",
        context="Detected family members: Alice, Bob",
        subtitle_dialogue=None
    )
    assert "=== User Guidance & Specific Focus Instructions ===" not in prompt
    assert "Alice, Bob" in prompt
    assert "Hello world" in prompt
    assert "00:00, 00:15" in prompt


def test_build_user_prompt_with_guidance():
    guidance = "Focus on hiking trails, Lake Louise, and Ben wearing a blue coat."
    prompt = build_user_prompt(
        timestamps=["00:05", "00:20"],
        audio_transcript=None,
        context=None,
        subtitle_dialogue=None,
        prompt_guidance=guidance
    )
    assert "=== User Guidance & Specific Focus Instructions ===" in prompt
    assert guidance in prompt
    assert "prioritize identifying these specific individuals, locations, actions" in prompt
    assert "00:05, 00:20" in prompt


def test_api_prompts_defaults():
    res = client.get("/api/prompts/defaults")
    assert res.status_code == 200
    data = res.json()
    assert "default_system_prompt" in data
    assert "JSON object" in data["default_system_prompt"]


def test_api_queue_prompt_guidance():
    res = client.post("/api/queue/prompt-guidance", json={"prompt_guidance": "Summer road trip"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["prompt_guidance"] == "Summer road trip"


def test_api_config_with_prompt_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    custom_sys = "Custom system instructions for testing"
    default_guide = "Permanent guidance for all videos"

    post_res = client.post("/api/config", json={
        "custom_system_prompt": custom_sys,
        "default_prompt_guidance": default_guide,
        "batch_prompt_guidance": "Current batch guidance"
    })
    assert post_res.status_code == 200
    cfg = post_res.json()["config"]
    assert cfg["custom_system_prompt"] == custom_sys
    assert cfg["default_prompt_guidance"] == default_guide
    assert cfg["batch_prompt_guidance"] == "Current batch guidance"

    get_res = client.get("/api/config")
    assert get_res.status_code == 200
    cfg_get = get_res.json()
    assert cfg_get["custom_system_prompt"] == custom_sys
    assert cfg_get["default_prompt_guidance"] == default_guide


def test_queue_add_with_prompt_guidance(tmp_path):
    video_file = tmp_path / "test_guidance_clip.mp4"
    video_file.write_bytes(b"dummy")

    res = client.post("/api/queue/add", json={
        "file_paths": [str(video_file)],
        "prompt_guidance": "Look for Grandma's 80th birthday cake"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["added_count"] == 1


def test_queue_manager_guidance_composition(tmp_path):
    qm = QueueManager()
    cfg = AppConfig()
    cfg.default_prompt_guidance = "Always note room lighting and camera angle."
    qm.config = cfg
    qm.batch_prompt_guidance = "Focus on the kids soccer match."

    # Test item with its own guidance
    task = TaskItem(
        filename="match.mp4",
        file_path=str(tmp_path / "match.mp4"),
        prompt_guidance="Spot jersey #7 and the coach."
    )

    guidance_parts = []
    if cfg.default_prompt_guidance and cfg.default_prompt_guidance.strip():
        guidance_parts.append(cfg.default_prompt_guidance.strip())
    if qm.batch_prompt_guidance and qm.batch_prompt_guidance.strip():
        bg = qm.batch_prompt_guidance.strip()
        if bg not in guidance_parts:
            guidance_parts.append(bg)
    if task.prompt_guidance and task.prompt_guidance.strip():
        tg = task.prompt_guidance.strip()
        if tg not in guidance_parts:
            guidance_parts.append(tg)

    combined = "\n\n".join(guidance_parts)
    assert "Always note room lighting" in combined
    assert "kids soccer match" in combined
    assert "Spot jersey #7" in combined


def test_ai_timeout_configuration_and_ollama_timeout():
    from src.ai.ollama_provider import OllamaVisionProvider
    from src.ai.base import FrameItem

    cfg = AppConfig(ai_timeout_seconds=900)
    assert cfg.ai_timeout_seconds == 900

    provider = OllamaVisionProvider(base_url="http://localhost:11434")

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        mock_res = MagicMock()
        mock_res.json.return_value = {
            "message": {
                "content": '{"title": "Test", "summary": "Sum", "events": [], "tags": [], "people_or_subjects": [], "animals_or_pets": [], "objects": [], "suggested_filename": "test"}'
            }
        }
        mock_instance.post.return_value = mock_res

        # Call with explicit 600s
        provider.describe_video(
            frames=[],
            timeout_seconds=600
        )

        called_timeout = mock_client_cls.call_args[1]["timeout"]
        assert called_timeout.read == 600.0


def test_build_user_prompt_with_slug_guidance():
    slug_guide = "Format as [category]_[action]_[detail] in lowercase with underscores, max 30 characters."
    prompt = build_user_prompt(
        timestamps=["00:00"],
        audio_transcript=None,
        context=None,
        subtitle_dialogue=None,
        prompt_guidance="Family vacation",
        slug_guidance=slug_guide
    )
    assert "=== AI Suggested Slug & Filename Naming Convention ===" in prompt
    assert slug_guide in prompt
    assert "suggested_filename" in prompt


def test_api_queue_slug_guidance():
    res = client.post("/api/queue/slug-guidance", json={"slug_guidance": "category_action_shot"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["slug_guidance"] == "category_action_shot"

    get_res = client.get("/api/queue/slug-guidance")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["batch_slug_guidance"] == "category_action_shot"


def test_api_config_with_slug_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    default_slug = "category_action_detail"
    batch_slug = "trip_location_shot"

    post_res = client.post("/api/config", json={
        "default_slug_guidance": default_slug,
        "batch_slug_guidance": batch_slug
    })
    assert post_res.status_code == 200
    cfg = post_res.json()["config"]
    assert cfg["default_slug_guidance"] == default_slug
    assert cfg["batch_slug_guidance"] == batch_slug


def test_queue_add_with_slug_guidance(tmp_path):
    video_file = tmp_path / "test_slug_clip.mp4"
    video_file.write_bytes(b"dummy")

    res = client.post("/api/queue/add", json={
        "file_paths": [str(video_file)],
        "prompt_guidance": "Vacation video",
        "slug_guidance": "vacation_location_action"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["added_count"] == 1

