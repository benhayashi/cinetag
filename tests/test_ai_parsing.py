from src.ai.prompt import parse_ai_response, build_user_prompt

def test_parse_json_markdown():
    raw = """
Here is the analysis:
```json
{
  "title": "Summer Beach Day",
  "summary": "Kids playing by the shore with sand castles.",
  "events": [
    {"timecode": "00:05", "description": "Waves splashing", "is_highlight": true}
  ],
  "tags": ["beach", "ocean", "sunshine"],
  "people_or_subjects": ["Kids"],
  "suggested_filename": "summer_beach_day"
}
```
Hope this helps!
"""
    res = parse_ai_response(raw)
    assert res.title == "Summer Beach Day"
    assert len(res.events) == 1
    assert res.events[0].is_highlight is True
    assert "beach" in res.tags
    assert res.suggested_filename == "summer_beach_day"

def test_parse_animals_and_objects():
    raw = """
```json
{
  "title": "Dog Playing Tennis",
  "summary": "Golden retriever fetching a tennis ball on the backyard lawn.",
  "events": [],
  "tags": ["outdoors", "fun"],
  "people_or_subjects": ["Boy in red cap"],
  "animals_or_pets": ["Golden Retriever"],
  "objects": ["tennis racket", "tennis ball"],
  "suggested_filename": "dog_playing_tennis"
}
```
"""
    res = parse_ai_response(raw)
    assert res.title == "Dog Playing Tennis"
    assert "Golden Retriever" in res.animals_or_pets
    assert "tennis racket" in res.objects
    assert "tennis ball" in res.objects
    assert "golden retriever" in res.tags  # Merged into search tags
    assert "tennis racket" in res.tags

def test_parse_plain_text_fallback():
    raw = """
00:10 Kids running into the water
★ 00:35 Big splash and laughter
01:10 Building sand castle
"""
    res = parse_ai_response(raw, default_title="Fallback Title")
    assert len(res.events) == 3
    assert res.events[0].timecode == "00:10"
    assert res.events[1].is_highlight is True
    assert res.events[1].timecode == "00:35"

def test_build_user_prompt():
    prompt = build_user_prompt(
        timestamps=["00:00", "00:10", "00:20"],
        audio_transcript="Hello world, having fun!",
        context="Trip to France"
    )
    assert "00:10" in prompt
    assert "Hello world" in prompt
    assert "Trip to France" in prompt
