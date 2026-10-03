import json
import os
from datetime import datetime
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.ai.prompt import parse_ai_response
from src.media.renamer import update_file_date_and_metadata
from src.server.queue_manager import manager, TaskItem

client = TestClient(app)

def test_parse_ai_response_detected_date_in_context():
    ai_json = """
    {
        "title": "Grandma 80th Birthday",
        "suggested_filename": "grandma_80th_birthday",
        "summary": "Family gathering celebrating grandmother 80th birthday with cake and singing.",
        "detected_date_in_context": "1994-07-23",
        "detected_date_evidence": "Wall calendar behind the dining table clearly displays July 23, 1994, and cake reads 'Happy 80th 1994'.",
        "events": [],
        "tags": ["birthday", "family"],
        "people_or_subjects": ["Grandma"],
        "animals_or_pets": [],
        "objects": ["birthday cake", "wall calendar"]
    }
    """
    res = parse_ai_response(ai_json)
    assert res.title == "Grandma 80th Birthday"
    assert res.detected_date_in_context == "1994-07-23"
    assert "July 23, 1994" in (res.detected_date_evidence or "")


def test_update_file_date_and_metadata_updates_sidecars_and_mtime(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_text("fake video content")

    info_json = tmp_path / "clip.info.json"
    info_data = {
        "file": {
            "name": "clip.mp4",
            "path": str(video),
            "metadata": {
                "creation_time": "1970-01-01T00:00:00",
                "date_source_used": "fallback"
            }
        },
        "analysis": {
            "title": "Family Picnic",
            "summary": "Picnic in the park",
            "detected_date_in_context": "1998-06-15",
            "detected_date_evidence": "Banner says June 15 1998"
        },
        "pending_date_proposal": {
            "proposed_date": "1998-06-15",
            "status": "pending"
        }
    }
    info_json.write_text(json.dumps(info_data, indent=2))

    nfo = tmp_path / "clip.nfo"
    nfo.write_text("<movie><title>Family Picnic</title><premiered>1970-01-01</premiered></movie>")

    txt = tmp_path / "clip.txt"
    txt.write_text("Date: 1970-01-01\nTitle: Family Picnic")

    # Update date
    res = update_file_date_and_metadata(
        video_path=video,
        new_date="1998-06-15",
        update_mtime=True,
        rename_to_new_date=False
    )

    assert res["status"] == "success"
    assert res["new_date"] == "1998-06-15T00:00:00"

    # Verify sidecar updates
    updated_info = json.loads(info_json.read_text(encoding="utf-8"))
    assert updated_info["file"]["metadata"]["creation_time"] == "1998-06-15T00:00:00"
    assert updated_info["file"]["metadata"]["date_source_used"] == "confirmed_update"
    assert "pending_date_proposal" not in updated_info

    updated_nfo = nfo.read_text(encoding="utf-8")
    assert "<premiered>1998-06-15</premiered>" in updated_nfo

    # Verify filesystem mtime was updated to 1998
    stat = video.stat()
    dt = datetime.fromtimestamp(stat.st_mtime)
    assert dt.year == 1998
    assert dt.month == 6
    assert dt.day == 15


def test_api_date_confirm_update_apply_and_dismiss(tmp_path):
    video = tmp_path / "home_movie.mp4"
    video.write_text("video")

    info_json = tmp_path / "home_movie.info.json"
    info_data = {
        "file": {
            "name": "home_movie.mp4",
            "path": str(video),
            "metadata": {"creation_time": "2005-01-01T00:00:00"}
        },
        "pending_date_proposal": {
            "proposed_date": "1995-12-25",
            "proposed_datetime_iso": "1995-12-25T10:00:00",
            "proposed_date_formatted": "December 25, 1995",
            "source": "context",
            "status": "pending"
        }
    }
    info_json.write_text(json.dumps(info_data, indent=2))

    # Add task to queue manager
    task = TaskItem(file_path=str(video), filename=video.name)
    task.result = {
        "title": "Christmas 1995",
        "pending_date_proposal": info_data["pending_date_proposal"],
        "date_used": "2005-01-01T00:00:00"
    }
    manager.queue.append(task)

    # Test Dismiss first
    res_dismiss = client.post("/api/date/confirm-update", json={
        "file_path": str(video),
        "action": "dismiss",
        "task_id": task.id
    })
    assert res_dismiss.status_code == 200
    assert res_dismiss.json()["status"] == "dismissed"
    assert task.result["pending_date_proposal"] is None

    # Re-arm proposal and test Apply
    task.result["pending_date_proposal"] = info_data["pending_date_proposal"]
    info_json.write_text(json.dumps(info_data, indent=2))

    res_apply = client.post("/api/date/confirm-update", json={
        "file_path": str(video),
        "action": "apply",
        "new_date": "1995-12-25T10:00:00",
        "task_id": task.id
    })
    assert res_apply.status_code == 200
    assert res_apply.json()["status"] == "success"
    assert task.result["date_used"] == "1995-12-25T10:00:00"

    # Cleanup task from queue
    if task in manager.queue:
        manager.queue.remove(task)


def test_api_get_results_returns_date_proposal_fields(tmp_path):
    video = tmp_path / "birthday_party.mp4"
    video.write_text("video")

    info_json = tmp_path / "birthday_party.info.json"
    info_data = {
        "file": {
            "name": "birthday_party.mp4",
            "path": str(video),
            "metadata": {
                "creation_time": "2004-01-01T00:00:00",
                "date_source_used": "metadata"
            }
        },
        "analysis": {
            "title": "Birthday Party",
            "summary": "Celebration",
            "detected_date_in_context": "1991-05-12",
            "detected_date_evidence": "Calendar on wall displays May 12, 1991"
        },
        "pending_date_proposal": {
            "proposed_date": "1991-05-12",
            "proposed_datetime_iso": "1991-05-12T00:00:00",
            "proposed_date_formatted": "May 12, 1991",
            "current_date": "2004-01-01",
            "current_date_formatted": "January 01, 2004",
            "source": "context",
            "evidence": "Calendar on wall displays May 12, 1991",
            "status": "pending"
        }
    }
    info_json.write_text(json.dumps(info_data, indent=2))

    res = client.get(f"/api/results?file_path={str(video)}")
    assert res.status_code == 200
    data = res.json()
    assert data["pending_date_proposal"] is not None
    assert data["pending_date_proposal"]["proposed_date"] == "1991-05-12"
    assert data["detected_date_in_context"] == "1991-05-12"
    assert "May 12, 1991" in data["detected_date_evidence"]


def test_queue_manager_update_and_dismiss_task_date():
    task = TaskItem(file_path="/tmp/fake_vid.mp4", filename="fake_vid.mp4")
    task.result = {
        "title": "Vid",
        "date_used": "2000-01-01T00:00:00",
        "pending_date_proposal": {
            "proposed_date": "1990-05-20",
            "status": "pending"
        }
    }
    manager.queue.append(task)
    try:
        # Dismiss test
        manager.dismiss_task_date_proposal("/tmp/fake_vid.mp4", task_id=task.id)
        assert task.result["pending_date_proposal"] is None

        # Re-arm proposal
        task.result["pending_date_proposal"] = {"proposed_date": "1990-05-20"}
        manager.update_task_date("/tmp/fake_vid.mp4", "1990-05-20T12:00:00", date_source="context", task_id=task.id)
        assert task.result["date_used"] == "1990-05-20T12:00:00"
        assert task.result["date_source_used"] == "context"
        assert task.result["pending_date_proposal"] is None
    finally:
        if task in manager.queue:
            manager.queue.remove(task)
