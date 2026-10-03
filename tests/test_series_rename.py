import json
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.media.renamer import format_enumeration, generate_series_rename_plan
from src.server.queue_manager import manager

client = TestClient(app)

def test_format_enumeration_styles():
    # Test pt
    assert format_enumeration(1, 3, "pt", 2) == "_pt01"
    assert format_enumeration(10, 20, "pt", 2) == "_pt10"
    # Test part
    assert format_enumeration(1, 3, "part", 2) == "_part01"
    # Test numeric
    assert format_enumeration(2, 5, "numeric", 2) == "_02"
    # Test hyphen
    assert format_enumeration(3, 5, "hyphen", 2) == "-03"
    # Test count
    assert format_enumeration(1, 3, "count", 2) == "_01_of_03"
    # Test title_part
    assert format_enumeration(1, 3, "title_part", 1) == " (Part 1)"
    # Test none
    assert format_enumeration(1, 3, "none", 2) == ""

def test_generate_series_rename_plan(tmp_path):
    clip1 = tmp_path / "clip_a.mp4"
    clip2 = tmp_path / "clip_b.mp4"
    clip1.write_text("v1")
    clip2.write_text("v2")

    items = [
        {"file_path": str(clip1), "creation_date": "2024-06-15 10:00:00", "title": "Beach Day"},
        {"file_path": str(clip2), "creation_date": "2024-06-15 11:30:00", "title": "Beach Sunset"},
    ]

    # 1. datetime_title_enum scheme
    plan = generate_series_rename_plan(
        items=items,
        series_title="Summer Vacation",
        scheme="datetime_title_enum",
        enum_style="pt",
        pad_digits=2,
        start_index=1
    )
    assert len(plan) == 2
    assert "_pt01.mp4" in plan[0]["target_filename"]
    assert "_pt02.mp4" in plan[1]["target_filename"]
    assert "Summer_Vacation" in plan[0]["target_filename"]
    assert plan[0]["title_with_part"] == "Summer Vacation (Part 1)"
    assert plan[1]["title_with_part"] == "Summer Vacation (Part 2)"

    # 2. ai_slug_enum scheme
    plan_slug = generate_series_rename_plan(
        items=items,
        series_title="Hawaii Trip",
        scheme="ai_slug_enum",
        enum_style="part",
        pad_digits=2,
        start_index=1
    )
    assert plan_slug[0]["target_filename"] == "hawaii_trip_part01.mp4"
    assert plan_slug[1]["target_filename"] == "hawaii_trip_part02.mp4"

    # 3. series_start time strategy: both items share first clip's date/time
    plan_sync_time = generate_series_rename_plan(
        items=items,
        series_title="Family Picnic",
        scheme="datetime_title_enum",
        enum_style="numeric",
        time_strategy="series_start"
    )
    # Both start with clip1's timestamp 20240615
    assert plan_sync_time[0]["target_filename"].startswith("20240615_")
    assert plan_sync_time[1]["target_filename"].startswith("20240615_")
    assert plan_sync_time[0]["target_filename"].endswith("_01.mp4")
    assert plan_sync_time[1]["target_filename"].endswith("_02.mp4")

def test_series_rename_plan_collision_prevention(tmp_path):
    # If a file already exists on disk that matches the target name,
    # the plan must automatically resolve collisions without conflicts.
    clip1 = tmp_path / "part_1.mp4"
    clip2 = tmp_path / "part_2.mp4"
    clip1.write_text("v1")
    clip2.write_text("v2")

    # Pre-create conflicting target on disk
    conflict = tmp_path / "road_trip_pt01.mp4"
    conflict.write_text("existing file")

    items = [
        {"file_path": str(clip1)},
        {"file_path": str(clip2)}
    ]

    plan = generate_series_rename_plan(
        items=items,
        series_title="Road Trip",
        scheme="ai_slug_enum",
        enum_style="pt"
    )

    # First clip cannot be road_trip_pt01.mp4 because it already exists on disk
    assert plan[0]["target_filename"] != "road_trip_pt01.mp4"
    assert plan[0]["conflict_detected"] is True
    # Targets for the two clips must also be mutually distinct
    assert plan[0]["target_filename"] != plan[1]["target_filename"]

def test_load_processed_videos_api(tmp_path):
    video1 = tmp_path / "trip_part1.mp4"
    video1.write_text("video 1")
    srt1 = tmp_path / "trip_part1.srt"
    srt1.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    info1 = tmp_path / "trip_part1.info.json"
    info1.write_text(json.dumps({
        "file": {"name": "trip_part1.mp4"},
        "analysis": {
            "title": "Trip Part 1 Arrival",
            "summary": "Arrived at the cabin",
            "tags": ["travel", "cabin"],
            "events": [{"time": "00:01", "description": "Arrival"}]
        }
    }))

    video2 = tmp_path / "trip_part2.mp4"
    video2.write_text("video 2")
    info2 = tmp_path / "trip_part2.info.json"
    info2.write_text(json.dumps({
        "file": {"name": "trip_part2.mp4"},
        "analysis": {
            "title": "Trip Part 2 Hiking",
            "summary": "Hiking on the trail",
            "tags": ["hiking", "mountains"]
        }
    }))

    res = client.post("/api/queue/load_processed", json={
        "file_paths": [str(tmp_path)]
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["loaded_count"] == 2

    # Check tasks exist in manager queue as completed
    loaded_files = [t.filename for t in manager.queue if t.status == "completed"]
    assert "trip_part1.mp4" in loaded_files
    assert "trip_part2.mp4" in loaded_files

def test_series_rename_preview_and_execute_api(tmp_path):
    # Setup test videos and sidecars
    v1 = tmp_path / "scene_one.mp4"
    v1.write_text("content 1")
    s1 = tmp_path / "scene_one.srt"
    s1.write_text("subtitle 1")
    j1 = tmp_path / "scene_one.info.json"
    j1.write_text(json.dumps({"analysis": {"title": "Scene One Old Title"}}))
    n1 = tmp_path / "scene_one.nfo"
    n1.write_text("<movie><title>Scene One Old Title</title></movie>")

    v2 = tmp_path / "scene_two.mp4"
    v2.write_text("content 2")
    s2 = tmp_path / "scene_two.srt"
    s2.write_text("subtitle 2")
    j2 = tmp_path / "scene_two.info.json"
    j2.write_text(json.dumps({"analysis": {"title": "Scene Two Old Title"}}))

    # Load them into queue
    client.post("/api/queue/load_processed", json={"file_paths": [str(tmp_path)]})

    # Find tasks in manager
    t1 = next(t for t in manager.queue if t.filename == "scene_one.mp4")
    t2 = next(t for t in manager.queue if t.filename == "scene_two.mp4")

    items_payload = [
        {
            "file_path": str(v1),
            "creation_date": "2024-07-04 12:00:00",
            "title": "Scene One Old Title",
            "task_id": t1.id
        },
        {
            "file_path": str(v2),
            "creation_date": "2024-07-04 14:00:00",
            "title": "Scene Two Old Title",
            "task_id": t2.id
        }
    ]

    # Preview
    preview_res = client.post("/api/rename/series/preview", json={
        "items": items_payload,
        "series_title": "Summer Festival",
        "scheme": "ai_slug_enum",
        "enum_style": "pt",
        "pad_digits": 2,
        "start_index": 1
    })
    assert preview_res.status_code == 200
    pdata = preview_res.json()
    assert pdata["total_items"] == 2
    assert pdata["plan"][0]["target_filename"] == "summer_festival_pt01.mp4"
    assert pdata["plan"][1]["target_filename"] == "summer_festival_pt02.mp4"

    # Execute
    exec_res = client.post("/api/rename/series/execute", json={
        "items": items_payload,
        "series_title": "Summer Festival",
        "scheme": "ai_slug_enum",
        "enum_style": "pt",
        "pad_digits": 2,
        "start_index": 1,
        "rename_sidecars": True,
        "update_metadata": True
    })
    assert exec_res.status_code == 200
    edata = exec_res.json()
    assert edata["status"] == "ok"
    assert edata["renamed_count"] == 2

    # Check files on disk
    new_v1 = tmp_path / "summer_festival_pt01.mp4"
    new_s1 = tmp_path / "summer_festival_pt01.srt"
    new_j1 = tmp_path / "summer_festival_pt01.info.json"
    new_n1 = tmp_path / "summer_festival_pt01.nfo"
    assert new_v1.exists()
    assert new_s1.exists()
    assert new_j1.exists()
    assert new_n1.exists()
    assert not v1.exists()

    new_v2 = tmp_path / "summer_festival_pt02.mp4"
    new_s2 = tmp_path / "summer_festival_pt02.srt"
    new_j2 = tmp_path / "summer_festival_pt02.info.json"
    assert new_v2.exists()
    assert new_s2.exists()
    assert new_j2.exists()
    assert not v2.exists()

    # Check updated metadata titles
    parsed_j1 = json.loads(new_j1.read_text())
    assert parsed_j1["analysis"]["title"] == "Summer Festival (Part 1)"
    assert "<title>Summer Festival (Part 1)</title>" in new_n1.read_text()

    parsed_j2 = json.loads(new_j2.read_text())
    assert parsed_j2["analysis"]["title"] == "Summer Festival (Part 2)"

    # Verify QueueManager tasks were updated
    assert t1.filename == "summer_festival_pt01.mp4"
    assert t1.result["title"] == "Summer Festival (Part 1)"
    assert t2.filename == "summer_festival_pt02.mp4"
    assert t2.result["title"] == "Summer Festival (Part 2)"
