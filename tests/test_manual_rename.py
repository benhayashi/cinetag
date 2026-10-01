import json
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.media.renamer import execute_rename
from src.server.queue_manager import manager, TaskItem

client = TestClient(app)

def test_execute_rename_updates_sidecars_and_metadata(tmp_path):
    # Setup dummy video and sidecars
    video_file = tmp_path / "clip_001.mp4"
    video_file.write_text("dummy video content")

    srt_file = tmp_path / "clip_001.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello World\n")

    txt_file = tmp_path / "clip_001.mp4.txt"
    txt_file.write_text("clip_001.mp4 — Original AI Title\n\nSome summary here.\n")

    info_json = tmp_path / "clip_001.info.json"
    info_data = {
        "file": {
            "name": "clip_001.mp4",
            "path": str(video_file)
        },
        "analysis": {
            "title": "Original AI Title",
            "summary": "Some summary here",
            "suggested_filename": "clip_001.mp4"
        }
    }
    info_json.write_text(json.dumps(info_data, indent=2))

    nfo_file = tmp_path / "clip_001.nfo"
    nfo_file.write_text("<movie><title>Original AI Title</title></movie>")

    # Another video file in the same directory should NOT be touched
    other_video = tmp_path / "clip_001.mov"
    other_video.write_text("other video")

    # Rename
    res = execute_rename(
        original_path=video_file,
        new_filename="20240501_Beach_Party.mp4",
        rename_sidecars=True,
        new_title="Beach Party Fun"
    )

    assert res["status"] == "success"
    new_video = tmp_path / "20240501_Beach_Party.mp4"
    assert new_video.exists()
    assert not video_file.exists()

    # Check sidecars renamed
    new_srt = tmp_path / "20240501_Beach_Party.srt"
    assert new_srt.exists()
    assert not srt_file.exists()

    new_txt = tmp_path / "20240501_Beach_Party.mp4.txt"
    assert new_txt.exists()
    assert "Beach Party Fun" in new_txt.read_text()

    new_json = tmp_path / "20240501_Beach_Party.info.json"
    assert new_json.exists()
    parsed_json = json.loads(new_json.read_text())
    assert parsed_json["file"]["name"] == "20240501_Beach_Party.mp4"
    assert parsed_json["analysis"]["title"] == "Beach Party Fun"

    new_nfo = tmp_path / "20240501_Beach_Party.nfo"
    assert new_nfo.exists()
    assert "<title>Beach Party Fun</title>" in new_nfo.read_text()

    # Unrelated video was NOT renamed
    assert other_video.exists()

def test_single_rename_api_preview_and_execute(tmp_path):
    video = tmp_path / "sample_vacation.mp4"
    video.write_text("dummy")

    srt = tmp_path / "sample_vacation.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nSub\n")

    txt = tmp_path / "sample_vacation.txt"
    txt.write_text("sample_vacation.mp4 — Old Title\n")

    # Add task to queue manager
    task = TaskItem(
        file_path=str(video),
        filename="sample_vacation.mp4",
        status="completed",
        result={
            "title": "Old Title",
            "suggested_filename": "sample_vacation.mp4",
            "final_file_path": str(video),
            "sidecars": [str(srt), str(txt)]
        }
    )
    manager.queue.append(task)

    # 1. Preview
    resp = client.post("/api/rename/single/preview", json={
        "file_path": str(video),
        "new_name": "Family Trip to Hawaii",
        "mode": "filename"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_filename"] == "Family Trip to Hawaii.mp4"
    assert "sample_vacation.srt" in data["sidecars_found"]
    assert "sample_vacation.txt" in data["sidecars_found"]

    # 2. Execute
    resp2 = client.post("/api/rename/single", json={
        "file_path": str(video),
        "new_name": "Family Trip to Hawaii",
        "mode": "filename",
        "rename_sidecars": True,
        "update_metadata": True,
        "task_id": task.id
    })
    assert resp2.status_code == 200
    res_data = resp2.json()
    assert res_data["status"] == "success"
    assert res_data["new_filename"] == "Family Trip to Hawaii.mp4"
    assert (tmp_path / "Family Trip to Hawaii.mp4").exists()
    assert (tmp_path / "Family Trip to Hawaii.srt").exists()

    # Check task was updated in memory
    assert task.filename == "Family Trip to Hawaii.mp4"
    assert task.result["title"] == "Family Trip to Hawaii"
    assert any("Family Trip to Hawaii.srt" in sc for sc in task.result["sidecars"])

def test_single_rename_title_mode_with_template(tmp_path):
    video = tmp_path / "20231120_153000_old_slug.mp4"
    video.write_text("dummy video")

    srt = tmp_path / "20231120_153000_old_slug.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nSub\n")

    info_json = tmp_path / "20231120_153000_old_slug.info.json"
    info_json.write_text(json.dumps({
        "file": {"name": video.name, "path": str(video)},
        "analysis": {"title": "Old Slug", "suggested_filename": video.name}
    }))

    resp = client.post("/api/rename/single", json={
        "file_path": str(video),
        "new_name": "Thanksgiving Dinner",
        "mode": "title",
        "rename_sidecars": True,
        "update_metadata": True,
        "template": "{date_compact}_{title}"
    })
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"
    # Should use date from filename 20231120
    assert "20231120" in res_data["new_filename"]
    assert "Thanksgiving_Dinner" in res_data["new_filename"]
    
    # Check on disk
    renamed_video = tmp_path / res_data["new_filename"]
    assert renamed_video.exists()
    assert not video.exists()

    # Check sidecar
    renamed_srt = tmp_path / f"{renamed_video.stem}.srt"
    assert renamed_srt.exists()

    # Check json updated
    renamed_json = tmp_path / f"{renamed_video.stem}.info.json"
    assert renamed_json.exists()
    data = json.loads(renamed_json.read_text())
    assert data["analysis"]["title"] == "Thanksgiving Dinner"

