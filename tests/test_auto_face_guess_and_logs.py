import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.core.config import AppConfig, load_config, save_config
from src.server.queue_manager import QueueManager, TaskItem
from src.media.renamer import generate_suggested_name
from src.media.faces import FaceRegistry

client = TestClient(app)

def test_resolve_local_subfolder_and_metadata(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    sub = desktop / "temp-videos-test"
    sub.mkdir(parents=True)
    vid = sub / "snow_play.mp4"
    vid_content = b"fake video bytes 12345"
    vid.write_bytes(vid_content)

    # Search with candidate folder desktop and file size metadata
    res = client.post("/api/files/resolve-local", json={
        "filenames": ["snow_play.mp4"],
        "files_meta": [{"name": "snow_play.mp4", "size": len(vid_content)}],
        "current_folder": str(desktop)
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["count"] == 1
    assert data["resolved_paths"] == [str(vid.resolve())]
    assert data["detected_folder"] == str(sub.resolve())

def test_persistent_logger_and_download():
    # Make a request to generate a log entry
    client.get("/api/status")

    res = client.get("/api/logs/download")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "attachment; filename=\"video_describer_logs_" in res.headers["content-disposition"]
    assert len(res.text) > 0

def test_face_auto_guess_names_protection(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    # Create an unnamed cluster
    now_iso = "2026-09-27T10:00:00"
    registry._data["person_001"] = {
        "id": "person_001",
        "name": "Person_01",
        "user_named": False,
        "ai_guessed": False,
        "embedding": [0.0] * 128,
        "video_count": 1,
        "video_paths": ["/tmp/v1.mp4"],
        "created_at": now_iso,
        "last_seen": now_iso
    }

    # Create a user-named person (must NEVER be overwritten)
    registry._data["person_002"] = {
        "id": "person_002",
        "name": "Grandpa Joe",
        "user_named": True,
        "ai_guessed": False,
        "embedding": [0.0] * 128,
        "video_count": 1,
        "video_paths": ["/tmp/v1.mp4"],
        "created_at": now_iso,
        "last_seen": now_iso
    }
    registry._save()

    # Correlate with AI people names
    matches = registry.correlate_and_guess_names(
        detected_face_ids=["person_001", "person_002"],
        ai_people_names=["Grandma Betty", "Someone New"],
        video_path="/tmp/v1.mp4",
        summary="Grandma Betty and Grandpa Joe are sitting together"
    )

    assert len(matches) == 1
    assert matches[0]["person_id"] == "person_001"
    assert matches[0]["old_name"] == "Person_01"
    assert matches[0]["new_name"] == "Grandma Betty"

    # Verify person_001 was updated
    all_faces = registry.get_all()
    p1 = next(f for f in all_faces if f["id"] == "person_001")
    assert p1["name"] == "Grandma Betty"
    assert p1["ai_guessed"] is True
    assert p1["user_named"] is False

    # Verify user-named person_002 was NOT overwritten
    p2 = next(f for f in all_faces if f["id"] == "person_002")
    assert p2["name"] == "Grandpa Joe"
    assert p2["user_named"] is True

def test_queue_clear_completed():
    qm = QueueManager()
    t1 = TaskItem(file_path="/tmp/v1.mp4", filename="v1.mp4", status="queued")
    t2 = TaskItem(file_path="/tmp/v2.mp4", filename="v2.mp4", status="processing")
    t3 = TaskItem(file_path="/tmp/v3.mp4", filename="v3.mp4", status="completed")
    t4 = TaskItem(file_path="/tmp/v4.mp4", filename="v4.mp4", status="completed")

    qm.queue = [t1, t2, t3, t4]
    removed = qm.clear_completed()

    assert removed == 2
    assert len(qm.queue) == 2
    assert qm.queue[0].filename == "v1.mp4"
    assert qm.queue[1].filename == "v2.mp4"

def test_timestamp_without_z():
    p = Path("video.mp4")
    name = generate_suggested_name(
        original_path=p,
        ai_title="Skiing Vacation",
        creation_date="2024-05-18T18:30:00Z",
        template="{date_compact}_{time_zulu}_{title}"
    )
    assert name == "20240518_183000_Skiing_Vacation.mp4"
    assert "Z" not in name.split("_")[1]


def test_clean_person_name():
    from src.media.faces import clean_person_name, is_descriptive

    # Direct quoted names with roles / descriptors
    assert clean_person_name("man/father 'Ben'") == "Ben"
    assert clean_person_name('father "Ben"') == "Ben"
    assert clean_person_name("'Ben'") == "Ben"
    assert clean_person_name('"Ben"') == "Ben"
    assert clean_person_name("“Ben”") == "Ben"

    # Parenthesized names and roles
    assert clean_person_name("father (Ben)") == "Ben"
    assert clean_person_name("man/father (Ben)") == "Ben"
    assert clean_person_name("Ben (father/man)") == "Ben"
    assert clean_person_name("Ben (father)") == "Ben"

    # Delimiter formats
    assert clean_person_name("father: Ben") == "Ben"
    assert clean_person_name("man/father - Ben") == "Ben"
    assert clean_person_name("man / Ben") == "Ben"
    assert clean_person_name("Ben / father") == "Ben"

    # Phrasing
    assert clean_person_name("a man named Ben") == "Ben"
    assert clean_person_name("boy called Tommy") == "Tommy"

    # Preserve role style
    assert clean_person_name("man/father 'Ben'", preserve_role=True) == "Ben (man/father)"
    assert clean_person_name("father (Ben)", preserve_role=True) == "Ben (father)"
    assert clean_person_name("Ben (father/man)", preserve_role=True) == "Ben (father/man)"

    # Pure names
    assert clean_person_name("Sarah") == "Sarah"
    assert clean_person_name("Grandma Betty") == "Grandma Betty"

    # Generic check
    assert is_descriptive("Young boy") is True
    assert is_descriptive("man/father") is True
    assert is_descriptive("Ben") is False
    assert is_descriptive("Grandma Betty") is False


def test_face_correlate_guesses_full_name_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    now_iso = "2026-09-27T10:00:00"
    registry._data["person_ben"] = {
        "id": "person_ben",
        "name": "Person_01",
        "user_named": False,
        "ai_guessed": False,
        "embedding": [0.0] * 128,
        "video_count": 1,
        "video_paths": ["/tmp/ben.mp4"],
        "created_at": now_iso,
        "last_seen": now_iso
    }
    registry._save()

    matches = registry.correlate_and_guess_names(
        detected_face_ids=["person_ben"],
        ai_people_names=["man/father 'Ben'"],
        video_path="/tmp/ben.mp4",
        summary="Ben playing basketball with his kids"
    )

    assert len(matches) == 1
    assert matches[0]["new_name"] == "Ben"
    assert registry._data["person_ben"]["name"] == "Ben"


def test_high_recognition_distance_slider(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    # Test setting high face_max_distance (e.g. 0.85 and 0.95)
    res = client.post("/api/config", json={
        "face_max_distance": 0.85
    })
    assert res.status_code == 200
    assert res.json()["config"]["face_max_distance"] == 0.85

    res2 = client.post("/api/faces/reindex", json={
        "max_distance": 0.90
    })
    assert res2.status_code == 200
    data = res2.json()
    assert data["status"] == "ok"
    assert data["active_max_distance"] == 0.90
    assert abs(data["active_threshold"] - 0.10) < 1e-4

