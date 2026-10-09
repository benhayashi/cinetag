import os
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.queue_manager import QueueManager, TaskItem
from src.ai.prompt import build_user_prompt
from src.media.renamer import format_enumeration

client = TestClient(app)

def test_build_user_prompt_coherent_context():
    prompt = build_user_prompt(
        timestamps=["00:00:01", "00:00:05"],
        audio_transcript="Hello world",
        coherent_context="This video is Part 2 of 4 in a coherent sequence.\nPreceding clip summary: The family arrives at the beach."
    )
    assert "=== Coherent Clip & Sequential Context ===" in prompt
    assert "Part 2 of 4" in prompt
    assert "The family arrives at the beach" in prompt

def test_add_to_queue_coherent_mode(tmp_path):
    qm = QueueManager()
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip3 = tmp_path / "clip3.mp4"
    clip1.write_text("c1")
    clip2.write_text("c2")
    clip3.write_text("c3")

    added = qm.add_to_queue(
        [str(clip1), str(clip2), str(clip3)],
        coherent_mode="same_event",
        series_title="Summer Roadtrip",
        auto_enumerate=True,
        enum_style="pt"
    )

    assert len(added) == 3
    s_id = added[0].series_id
    assert s_id is not None
    assert s_id.startswith("coherent_")

    for idx, task in enumerate(added):
        assert task.series_id == s_id
        assert task.series_index == idx + 1
        assert task.series_total == 3
        assert task.coherent_mode == "same_event"
        assert task.series_title == "Summer Roadtrip"
        assert task.auto_enumerate is True
        assert task.enum_style == "pt"

    assert s_id in qm._coherent_group_state
    state = qm._coherent_group_state[s_id]
    assert state["series_title"] == "Summer Roadtrip"
    assert state["coherent_mode"] == "same_event"
    assert state["auto_enumerate"] is True
    assert state["people"] == []

def test_add_to_queue_independent_mode(tmp_path):
    qm = QueueManager()
    clip1 = tmp_path / "clip_ind1.mp4"
    clip2 = tmp_path / "clip_ind2.mp4"
    clip1.write_text("c1")
    clip2.write_text("c2")

    added = qm.add_to_queue(
        [str(clip1), str(clip2)],
        coherent_mode="none",
        auto_enumerate=False
    )

    assert len(added) == 2
    for task in added:
        assert task.series_id is None
        assert task.coherent_mode == "none"
        assert task.auto_enumerate is False

def test_api_queue_add_with_coherent_parameters(tmp_path):
    clip1 = tmp_path / "api_clip1.mp4"
    clip2 = tmp_path / "api_clip2.mp4"
    clip1.write_text("data1")
    clip2.write_text("data2")

    payload = {
        "file_paths": [str(clip1), str(clip2)],
        "conflict_mode": "overwrite",
        "coherent_mode": "same_people",
        "series_title": "Family Reunion",
        "auto_enumerate": True,
        "enum_style": "part"
    }

    res = client.post("/api/queue/add", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["added_count"] == 2

def test_coherent_state_accumulation():
    qm = QueueManager()
    s_id = "test_series_123"
    qm._coherent_group_state[s_id] = {
        "series_title": "Trip",
        "coherent_mode": "both",
        "people": ["Alice"],
        "previous_summary": None,
        "previous_title": None,
        "clips_completed": 0,
        "auto_enumerate": True,
        "enum_style": "pt"
    }

    # Simulate clip 1 completing and updating state
    state = qm._coherent_group_state[s_id]
    state["clips_completed"] += 1
    state["previous_summary"] = "Alice explores the museum entrance."
    state["previous_title"] = "Museum Entrance"
    for p in ["Alice", "Bob"]:
        if p not in state["people"]:
            state["people"].append(p)

    assert state["clips_completed"] == 1
    assert state["previous_summary"] == "Alice explores the museum entrance."
    assert state["people"] == ["Alice", "Bob"]
