from pathlib import Path
from src.media.renamer import (
    normalize_title_acronyms_and_numbers,
    truncate_at_word_boundary,
    generate_suggested_name,
    sanitize_filename
)
from src.ai.prompt import get_system_prompt, parse_ai_response

def test_normalize_written_numbers_to_digits():
    assert normalize_title_acronyms_and_numbers("Three Boys Playing Tennis") == "3 Boys Playing Tennis"
    assert normalize_title_acronyms_and_numbers("two dogs and one cat") == "2 dogs and 1 cat"
    assert normalize_title_acronyms_and_numbers("Ten Little Ducklings") == "10 Little Ducklings"
    assert normalize_title_acronyms_and_numbers("First Steps of Toddler") == "1st Steps of Toddler"
    assert normalize_title_acronyms_and_numbers("Second Birthday Party") == "2nd Birthday Party"


def test_normalize_age_phrases_to_yo():
    # Number words + age phrase
    assert normalize_title_acronyms_and_numbers("Three-Year-Old Boy") == "3yo Boy"
    assert normalize_title_acronyms_and_numbers("three year old girl") == "3yo girl"
    assert normalize_title_acronyms_and_numbers("4 years old toddler") == "4yo toddler"
    assert normalize_title_acronyms_and_numbers("5-yr-old playing in sandbox") == "5yo playing in sandbox"
    assert normalize_title_acronyms_and_numbers("Baby 18 months old / 2yo") == "Baby 18 months old / 2yo"


def test_normalize_common_acronyms():
    assert normalize_title_acronyms_and_numbers("Trip to the United States of America") == "Trip to the USA"
    assert normalize_title_acronyms_and_numbers("Touring New York City") == "Touring NYC"
    assert normalize_title_acronyms_and_numbers("Visiting the United Kingdom") == "Visiting the UK"
    assert normalize_title_acronyms_and_numbers("Flight between Los Angeles and San Francisco") == "Flight between LA and SF"


def test_truncate_at_word_boundary_never_cuts_word_in_half():
    # Title where index 50 falls in the middle of 'Christmas'
    title = "Family_Vacation_At_Yosemite_National_Park_With_Christmas_Tree"
    # Slicing at 50 would be "Family_Vacation_At_Yosemite_National_Park_With_Ch"
    truncated = truncate_at_word_boundary(title, 50)
    assert not truncated.endswith("Ch")
    assert truncated == "Family_Vacation_At_Yosemite_National_Park_With"

    # Title where index 25 falls in the middle of 'Celebration'
    short_title = "Birthday_Party_Celebration_Fun"
    # Slicing at 25 would be "Birthday_Party_Celebratio"
    truncated_short = truncate_at_word_boundary(short_title, 25)
    assert not truncated_short.endswith("Celebratio")
    assert truncated_short == "Birthday_Party"


def test_truncate_at_word_boundary_edge_cases():
    # Already short
    assert truncate_at_word_boundary("Short_Clip", 30) == "Short_Clip"
    # Exactly max_length
    assert truncate_at_word_boundary("Exactly_Ten", 11) == "Exactly_Ten"
    # One long word with no delimiter falls back safely without crash
    assert truncate_at_word_boundary("Supercalifragilisticexpialidocious", 10) == "Supercalif"


def test_generate_suggested_name_with_normalization_and_truncation():
    p = Path("video.mp4")
    # Combination of written numbers, age phrase, and acronym
    suggested = generate_suggested_name(
        original_path=p,
        ai_title="Three-Year-Old Boy Vacation in New York City",
        creation_date="2024-06-15T10:00:00",
        template="{date}_{title}",
        max_title_length=50
    )
    # "Three-Year-Old" -> "3yo", "New York City" -> "NYC"
    assert "3yo_Boy_Vacation_in_NYC" in suggested

    # Test with aggressive max_title_length (e.g. 15 chars) to ensure no cut-off word
    suggested_tight = generate_suggested_name(
        original_path=p,
        ai_title="Three-Year-Old Boy Vacation in New York City",
        creation_date="2024-06-15T10:00:00",
        template="{date}_{title}",
        max_title_length=15
    )
    # Title portion should truncate cleanly at word boundary
    title_part = suggested_tight.replace("2024-06-15_", "").replace(".mp4", "")
    assert not title_part.endswith("Vacat")
    assert title_part == "3yo_Boy"


def test_prompt_rules_contain_numeric_and_acronym_guidance():
    prompt = get_system_prompt()
    assert "numeric digits (0-9)" in prompt
    assert "Concise Acronyms & Abbreviations" in prompt
    assert "yo" in prompt
    assert "USA" in prompt
    assert "NEVER ends abruptly or in the middle of a word" in prompt


def test_fallback_parser_word_boundary_title():
    # Simulates a raw non-JSON AI output with a long first line
    long_line = "This is a really long description line from an AI model that didn't output JSON and goes on forever"
    res = parse_ai_response(long_line)
    # Must not end in the middle of a word
    assert not res.title.endswith("mod")
    assert len(res.title) <= 60


def test_sanitize_filename_cleans_possessives_and_punctuation():
    # Apostrophes should become 's' rather than '_s' or breaking filesystems
    # Punctuation like colons, exclamation marks, and quotes should be cleanly stripped
    raw = ' "Grandma\'s 80th Birthday: A Great Celebration!" '
    sanitized = sanitize_filename(raw)
    assert sanitized == "Grandmas_80th_Birthday_A_Great_Celebration"
    assert "'" not in sanitized
    assert ":" not in sanitized
    assert "!" not in sanitized
    assert '"' not in sanitized


def test_parse_ai_response_cleans_quotes_and_trailing_punctuation():
    json_ai = """{
        "title": "\\"Tommy's Soccer Match Championship!\\":",
        "suggested_filename": "\\"tommy_soccer_championship_goal\\" ",
        "summary": "Tommy playing soccer and scoring the winning goal."
    }"""
    res = parse_ai_response(json_ai)
    # Surrounding quotes and trailing colons/dashes stripped
    assert res.title == "Tommy's Soccer Match Championship!"
    assert res.suggested_filename == "tommy_soccer_championship_goal"


def test_prompt_rules_for_title_and_slug_detail():
    prompt = get_system_prompt()
    # Check AI Slug detail instruction
    assert "AI Suggested Filename Slug" in prompt
    assert "Include key details such as recognized person/family names" in prompt
    assert "grandma_betty_80th_birthday" in prompt
    # Check title conciseness and character cleanliness instruction
    assert "strictly 3-5 words in title case" in prompt
    assert "DO NOT use quotation marks, colons, semicolons" in prompt
