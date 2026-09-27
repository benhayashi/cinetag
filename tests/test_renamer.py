from pathlib import Path
from src.media.renamer import (
    sanitize_filename,
    generate_suggested_name,
    execute_rename,
    undo_last_rename
)

def test_sanitize_filename():
    unsafe = '  Summer: Vacation & BBQ? / <Trip>*  '
    safe = sanitize_filename(unsafe)
    assert ":" not in safe
    assert "?" not in safe
    assert "/" not in safe
    assert "<" not in safe
    assert ">" not in safe
    assert "*" not in safe
    assert not safe.startswith(" ")
    assert not safe.endswith(" ")

def test_suggested_name_template():
    p = Path("DCIM_1001.MP4")
    name = generate_suggested_name(
        original_path=p,
        ai_title="Beach Sunset Walk",
        creation_date="2024-07-15T18:30:00",
        template="{date}_{title}"
    )
    assert name == "2024-07-15_Beach_Sunset_Walk.mp4"

def test_execute_and_undo_rename(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    video = tmp_path / "clip.mp4"
    video.write_text("dummy video")
    sidecar = tmp_path / "clip.mp4.txt"
    sidecar.write_text("dummy description")

    res = execute_rename(video, "2024-07-15_party.mp4")
    assert res["status"] == "success"
    new_video = Path(res["renamed_to"])
    assert new_video.exists()
    assert not video.exists()
    # Check sidecar also moved
    new_sidecar = tmp_path / "2024-07-15_party.mp4.txt"
    assert new_sidecar.exists()

    # Now Undo
    undo_res = undo_last_rename()
    assert undo_res is not None
    assert video.exists()
    assert not new_video.exists()
    assert sidecar.exists()

def test_serialized_numerator_collision(tmp_path):
    # Existing target file
    existing = tmp_path / "2024-07-15_party.mp4"
    existing.write_text("existing video")

    # Second file to rename
    video2 = tmp_path / "clip2.mp4"
    video2.write_text("video 2")

    res = execute_rename(video2, "2024-07-15_party.mp4")
    assert res["status"] == "success"
    # Must use zero-padded serialized numerator _01
    assert Path(res["renamed_to"]).name == "2024-07-15_party_01.mp4"
    assert (tmp_path / "2024-07-15_party_01.mp4").exists()
    assert existing.exists()

    # Third file to rename -> must become _02
    video3 = tmp_path / "clip3.mp4"
    video3.write_text("video 3")
    res3 = execute_rename(video3, "2024-07-15_party.mp4")
    assert Path(res3["renamed_to"]).name == "2024-07-15_party_02.mp4"
    assert (tmp_path / "2024-07-15_party_02.mp4").exists()

def test_naming_schemes_and_collection_context():
    p = Path("/home/user/Videos/Hawaii_Vacation/GOPR0042.MP4")
    
    # Folder + Date + Title
    name1 = generate_suggested_name(
        original_path=p,
        ai_title="Snorkeling with Sea Turtles",
        creation_date="2024-08-10T14:30:15",
        template="{folder}_{date}_{title}",
        collection_name="Hawaii_Trip"
    )
    assert name1 == "Hawaii_Trip_2024-08-10_Snorkeling_with_Sea_Turtles.mp4"

    # AI slug template
    name2 = generate_suggested_name(
        original_path=p,
        ai_title="Snorkeling with Sea Turtles",
        suggested_slug="turtle_snorkeling_reef",
        template="{ai_slug}"
    )
    assert name2 == "turtle_snorkeling_reef.mp4"

    # Original + Title
    name3 = generate_suggested_name(
        original_path=p,
        ai_title="Snorkeling with Sea Turtles",
        template="{original}_{title}"
    )
    assert name3 == "GOPR0042_Snorkeling_with_Sea_Turtles.mp4"

def test_compact_date_zulu_time_and_names():
    p = Path("GOPR0042.MP4")
    # Date: 2024-05-18T14:30:45Z
    name = generate_suggested_name(
        original_path=p,
        ai_title="Birthday Cake Celebration",
        creation_date="2024-05-18T14:30:45Z",
        template="{date_compact}_{time_zulu}_{names}_{title}",
        people_names=["Grandma Rose", "Uncle Bob"],
        max_title_length=30
    )
    assert name == "20240518_143045_Grandma_Rose_Uncle_Bob_Birthday_Cake_Celebration.mp4"

def test_max_title_length_truncation():
    p = Path("clip.mp4")
    name = generate_suggested_name(
        original_path=p,
        ai_title="This Is A Very Very Long Title That Should Be Truncated Cleanly",
        creation_date="2024-05-18T12:00:00",
        template="{date_compact}_{title}",
        max_title_length=20
    )
    # The title portion is truncated to 20 chars
    assert len("This_Is_A_Very_Very_") == 20
    assert name == "20240518_This_Is_A_Very_Very.mp4"

def test_extract_datetime_from_filename():
    from src.media.renamer import extract_datetime_from_filename
    from datetime import datetime

    assert extract_datetime_from_filename("20150522_230949_001.mp4") == datetime(2015, 5, 22, 23, 9, 49)
    assert extract_datetime_from_filename("VID_20150727_183114.mp4") == datetime(2015, 7, 27, 18, 31, 14)
    assert extract_datetime_from_filename("2020-05-15_14-30-00.mov") == datetime(2020, 5, 15, 14, 30, 0)
    assert extract_datetime_from_filename("20181225_christmas.mkv") == datetime(2018, 12, 25, 0, 0, 0)
    assert extract_datetime_from_filename("vacation_random_no_date.mp4") is None

def test_resolve_datetime_smart_overrides_bad_2004_metadata():
    from src.media.renamer import resolve_datetime
    from datetime import datetime

    p = Path("20150522_230949_001.mp4")
    # Metadata has bad camera reset date 2004-02-09
    dt_loc, _, source = resolve_datetime(
        original_path=p,
        creation_date="2004-02-09T18:16:14.000000Z",
        date_source="smart"
    )
    # Smart mode detects that 2004 is <= 2005 while filename has valid 2015
    assert dt_loc == datetime(2015, 5, 22, 23, 9, 49)
    assert source == "filename"

def test_resolve_datetime_manual_override():
    from src.media.renamer import resolve_datetime
    from datetime import datetime

    p = Path("clip.mp4")
    dt_loc, _, source = resolve_datetime(
        original_path=p,
        creation_date="2004-02-09T18:16:14Z",
        date_override="2016-10-31 20:00:00",
        date_source="smart"
    )
    assert dt_loc == datetime(2016, 10, 31, 20, 0, 0)
    assert source == "override"

def test_generate_suggested_name_with_override_and_filename_date():
    from src.media.renamer import generate_suggested_name

    p = Path("20150522_230949_001.mp4")
    # 1. With smart fallback against 2004 metadata
    name1 = generate_suggested_name(
        original_path=p,
        ai_title="Save me",
        creation_date="2004-02-09T18:16:14Z",
        template="{date_compact}_{time_zulu}_{title}",
        date_source="smart"
    )
    assert name1 == "20150522_230949_Save_me.mp4"

    # 2. With manual date override
    name2 = generate_suggested_name(
        original_path=p,
        ai_title="Save me",
        creation_date="2004-02-09T18:16:14Z",
        template="{date_compact}_{time_zulu}_{title}",
        date_override="2017-08-14 12:00:00"
    )
    assert name2 == "20170814_120000_Save_me.mp4"

def test_execute_rename_syncs_info_json_metadata(tmp_path):
    import json
    from src.media.renamer import execute_rename

    vid = tmp_path / "old_clip.mp4"
    vid.write_text("video")
    info = tmp_path / "old_clip.info.json"
    info.write_text(json.dumps({
        "file": {
            "name": "old_clip.mp4",
            "metadata": {"creation_time": "2004-02-09T18:16:14Z"}
        }
    }))

    res = execute_rename(
        vid,
        "new_clip.mp4",
        new_creation_date="2015-05-22T23:09:49"
    )
    assert res["status"] == "success"
    new_info = tmp_path / "new_clip.info.json"
    assert new_info.exists()
    data = json.loads(new_info.read_text())
    assert data["file"]["name"] == "new_clip.mp4"
    assert data["file"]["metadata"]["creation_time"] == "2015-05-22T23:09:49"



