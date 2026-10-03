from datetime import datetime
from pathlib import Path
import pytest
from src.media.renamer import (
    extract_datetime_from_filename,
    extract_filename_context,
    format_filename_context_prompt,
    resolve_datetime,
    generate_suggested_name
)
from src.ai.prompt import build_user_prompt
from src.server.queue_manager import QueueManager, TaskItem
from src.server.api import AddQueueRequest


def test_extract_datetime_various_formats():
    # 1. ISO YYYY-MM-DD and compact
    dt1 = extract_datetime_from_filename("2021-08-15_Family_Dinner.mp4")
    assert dt1 == datetime(2021, 8, 15, 0, 0, 0)

    dt2 = extract_datetime_from_filename("VID_20150522_230949.mp4")
    assert dt2 == datetime(2015, 5, 22, 23, 9, 49)

    dt3 = extract_datetime_from_filename("20230518.mp4")
    assert dt3 == datetime(2023, 5, 18, 0, 0, 0)

    # 2. US Month-Day-Year (MM-DD-YYYY)
    dt_us = extract_datetime_from_filename("10-25-2018_Sarah_Birthday.mp4", order_preference="auto")
    assert dt_us == datetime(2018, 10, 25, 0, 0, 0)

    # 3. International Day-Month-Year (DD-MM-YYYY) - Day > 12 auto-detected
    dt_intl = extract_datetime_from_filename("25-10-2018_Paris_Trip.mp4", order_preference="auto")
    assert dt_intl == datetime(2018, 10, 25, 0, 0, 0)

    # 4. Ambiguous date disambiguation via order_preference
    dt_ambig_mdy = extract_datetime_from_filename("04-05-2022_Picnic.mp4", order_preference="mdy")
    assert dt_ambig_mdy == datetime(2022, 4, 5, 0, 0, 0)

    dt_ambig_dmy = extract_datetime_from_filename("04-05-2022_Picnic.mp4", order_preference="dmy")
    assert dt_ambig_dmy == datetime(2022, 5, 4, 0, 0, 0)

    # 5. Named months
    dt_month1 = extract_datetime_from_filename("July_2019_Hawaii.mp4")
    assert dt_month1 == datetime(2019, 7, 1, 0, 0, 0)

    dt_month2 = extract_datetime_from_filename("15_Aug_2021_Hiking.mp4")
    assert dt_month2 == datetime(2021, 8, 15, 0, 0, 0)

    dt_month3 = extract_datetime_from_filename("Oct-10-2020_Soccer.mov")
    assert dt_month3 == datetime(2020, 10, 10, 0, 0, 0)


def test_extract_filename_context():
    # Filename with people and location
    info = extract_filename_context("2019-08-12_Dad_and_Sarah_at_Disneyland.mp4")
    assert info["detected_date"] == datetime(2019, 8, 12, 0, 0, 0)
    assert info["detected_date_str"] == "2019-08-12"
    assert "Dad" in info["potential_names"]
    assert "Sarah" in info["potential_names"]
    assert "Disneyland" in info["potential_names"]
    assert info["has_meaningful_clues"] is True
    assert "Dad and Sarah at Disneyland" == info["cleaned_text"]

    # Filename with wedding and US date
    info2 = extract_filename_context("John_and_Emily_Wedding_Reception_10-25-2018.mov", date_order="mdy")
    assert info2["detected_date"] == datetime(2018, 10, 25, 0, 0, 0)
    assert "John" in info2["potential_names"]
    assert "Emily" in info2["potential_names"]
    assert "Wedding" in info2["potential_names"]
    assert info2["has_meaningful_clues"] is True

    # Camera filename without textual clues
    info3 = extract_filename_context("VID_20220415_120000.mp4")
    assert info3["detected_date"] == datetime(2022, 4, 15, 12, 0, 0)
    assert info3["cleaned_text"] == ""
    assert info3["potential_names"] == []
    assert info3["has_meaningful_clues"] is False


def test_format_filename_context_prompt():
    info = extract_filename_context("10-25-2018_Sarah_5th_Birthday_Party.mp4", date_order="auto")
    prompt_block = format_filename_context_prompt(info)
    assert prompt_block is not None
    assert "=== Original Filename Context & Clues ===" in prompt_block
    assert "10-25-2018_Sarah_5th_Birthday_Party.mp4" in prompt_block
    assert "Sarah" in prompt_block
    assert "Birthday" in prompt_block
    assert "Direct AI Slug" in prompt_block

    # Camera file has date clue only
    cam_info = extract_filename_context("VID_20220415_120000.mp4")
    cam_prompt = format_filename_context_prompt(cam_info)
    assert cam_prompt is not None
    assert "VID_20220415_120000.mp4" in cam_prompt
    assert "April 15, 2022" in cam_prompt

    # Empty filename returns None
    empty_prompt = format_filename_context_prompt(extract_filename_context(""))
    assert empty_prompt is None


def test_build_user_prompt_with_filename_context():
    timestamps = ["00:00", "00:05"]
    fn_ctx = "=== Original Filename Context & Clues ===\nOriginal filename: sample.mp4"
    prompt = build_user_prompt(timestamps, filename_context=fn_ctx)
    assert "=== Original Filename Context & Clues ===" in prompt
    assert "sample.mp4" in prompt


def test_resolve_datetime_with_date_order(tmp_path):
    f = tmp_path / "04-05-2022_Trip.mp4"
    f.touch()

    # MDY resolves to April 5
    dt_local_mdy, _, src_mdy = resolve_datetime(original_path=f, date_source="filename", date_order="mdy")
    assert dt_local_mdy.month == 4
    assert dt_local_mdy.day == 5
    assert src_mdy == "filename"

    # DMY resolves to May 4
    dt_local_dmy, _, src_dmy = resolve_datetime(original_path=f, date_source="filename", date_order="dmy")
    assert dt_local_dmy.month == 5
    assert dt_local_dmy.day == 4
    assert src_dmy == "filename"


def test_generate_suggested_name_with_date_order(tmp_path):
    f = tmp_path / "04-05-2022_Trip.mp4"
    f.touch()

    name_mdy = generate_suggested_name(
        original_path=f,
        ai_title="Trip",
        template="{date}_{title}",
        date_source="filename",
        date_order="mdy"
    )
    assert name_mdy == "2022-04-05_Trip.mp4"

    name_dmy = generate_suggested_name(
        original_path=f,
        ai_title="Trip",
        template="{date}_{title}",
        date_source="filename",
        date_order="dmy"
    )
    assert name_dmy == "2022-05-04_Trip.mp4"


def test_queue_add_with_filename_context_fields(tmp_path):
    f = tmp_path / "video1.mp4"
    f.touch()

    qm = QueueManager()
    tasks = qm.add_to_queue(
        [str(f)],
        use_filename_context=True,
        filename_date_order="mdy"
    )
    assert len(tasks) == 1
    assert tasks[0].use_filename_context is True
    assert tasks[0].filename_date_order == "mdy"

    # Verify AddQueueRequest model
    req = AddQueueRequest(
        file_paths=[str(f)],
        use_filename_context=False,
        filename_date_order="dmy"
    )
    assert req.use_filename_context is False
    assert req.filename_date_order == "dmy"
