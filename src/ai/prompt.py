import json
import re
from typing import Dict, Any, List, Optional
from src.ai.base import VideoAnalysisResult, TimestampEvent

SYSTEM_PROMPT = """You are an expert video archivist and editor assistant analyzing footage from private and home video collections.
Analyze the provided sequential video frames and audio transcript to understand the content of the clip.

You must respond in valid JSON with the following structure:
{
  "title": "Brief descriptive title (3-5 words in title case, e.g. Kids Backyard Tennis Match)",
  "summary": "Thorough paragraph explaining who is there, what is happening, the environment, actions, lighting, and general mood.",
  "events": [
    {
      "timecode": "00:00",
      "description": "Short description of what happens at this timestamp",
      "is_highlight": false
    }
  ],
  "tags": ["tennis", "backyard", "summer", "sports", "recreation"],
  "people_or_subjects": ["Young boy", "Teenage girl"],
  "animals_or_pets": ["Golden Retriever", "Border Collie"],
  "objects": ["tennis racket", "tennis ball", "sports visor", "lawn chair"],
  "suggested_filename": "kids_playing_tennis_backyard",
  "detected_date_in_context": "YYYY-MM-DD, YYYY-MM, or YYYY if a calendar, on-screen timestamp, newspaper, banner, or spoken date is present; otherwise null",
  "detected_date_evidence": "Short explanation of the date evidence (e.g. Wall calendar shows October 2014, or Camcorder overlay in corner shows 05/12/1998); otherwise null"
}

Important Rules:
1. Ground your descriptions strictly on what is visible in the frames and heard in the audio.
2. If animals or pets (especially dogs or cats) are present, list them in "animals_or_pets" with specific breed or type whenever identifiable (e.g. "Golden Retriever", "Beagle", "Bulldog", "Pug", "Tabby Cat").
3. In "objects", list prominent physical items, sports gear, equipment, instruments, tools, or vehicles (e.g. "tennis racket", "acoustic guitar", "bicycle", "skateboard", "camera").
4. If key moments stand out as memorable or exciting, set "is_highlight": true.
5. AI Suggested Filename Slug: Compose 'suggested_filename' as a descriptive, balanced 3-5 word slug in lowercase with underscores, without file extension or dates. CRITICAL: Include key details such as recognized person/family names, locations, and the specific action or event (e.g. 'grandma_betty_80th_birthday', 'johnny_soccer_goal', 'family_hiking_yosemite', 'sarah_beach_sunset', not vague generic words like 'birthday' or 'playing').
6. Number Formatting: ALWAYS use numeric digits (0-9) instead of written words for numbers and counts (e.g. use "3" instead of "three", "2" instead of "two", "5yo" instead of "five year old", "1st" instead of "first") across titles, summaries, tags, people/subject labels, and event descriptions to conserve character limits.
7. Concise Acronyms & Abbreviations: Use common acronyms and abbreviations in titles and descriptions where applicable to save characters (e.g. "yo" for "year old" like "3yo boy", "USA" for "United States of America", "NYC" for "New York City", "UK", "bday" for "birthday", "Xmas" for "Christmas").
8. Title Quality: Keep titles complete, descriptive, and concise (strictly 3-5 words in title case). DO NOT use quotation marks, colons, semicolons, dashes, exclamation marks, or conversational filler (e.g. use 'Grandma 80th Birthday Party', 'Johnny Scoring Soccer Goal', not 'Our Amazing Vacation: A Fun Day!'). Ensure the title is a finished thought and NEVER ends abruptly or in the middle of a word.
9. Output ONLY the raw JSON object, without introductory text or markdown formatting if possible.
10. Filename Clues & Historical Metadata: When original filename context clues (such as people's names, event titles, locations, or dates) are provided, verify them against visual and audible cues. If consistent with the footage, incorporate them into "people_or_subjects", the "title", the "summary", "tags", and "suggested_filename".
11. Date & Time Clues in Video Context: Look closely for any visible or audible date/time information in the footage (e.g. wall or desk calendar with visible month/year/day, camcorder timestamp overlay in corner, newspaper date, event banners like 'Class of 2012' or '50th Anniversary 1998', birthday cakes, holiday decorations, or spoken dates in speech). If detected, report 'detected_date_in_context' (format as YYYY-MM-DD, YYYY-MM, or YYYY) and 'detected_date_evidence' (e.g. 'Wall calendar shows October 2014'). If no date information is detected in context, set both to null.
"""
DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT

def get_system_prompt(custom_prompt: Optional[str] = None) -> str:
    """Return active system prompt, falling back to DEFAULT_SYSTEM_PROMPT if custom_prompt is empty."""
    if custom_prompt and custom_prompt.strip():
        return custom_prompt.strip()
    return DEFAULT_SYSTEM_PROMPT

def build_user_prompt(
    timestamps: List[str],
    audio_transcript: Optional[str] = None,
    context: Optional[str] = None,
    subtitle_dialogue: Optional[str] = None,
    prompt_guidance: Optional[str] = None,
    slug_guidance: Optional[str] = None,
    filename_context: Optional[str] = None,
    coherent_context: Optional[str] = None
) -> str:
    parts = ["Here are the sampled video frames taken at timestamps: " + ", ".join(timestamps) + "."]
    
    if subtitle_dialogue and subtitle_dialogue.strip():
        parts.append(f"\nSubtitles dialogue (from accompanying .srt or embedded track):\n\"\"\"\n{subtitle_dialogue.strip()}\n\"\"\"")

    if audio_transcript and audio_transcript.strip():
        parts.append(f"\nAudio transcript of the video:\n\"\"\"\n{audio_transcript.strip()}\n\"\"\"")
    elif not subtitle_dialogue:
        parts.append("\n(No speech or audio dialogue detected in this clip)")

    if context and context.strip():
        parts.append(f"\nAdditional context about the video/people:\n{context.strip()}")

    if filename_context and filename_context.strip():
        parts.append(f"\n{filename_context.strip()}")

    if coherent_context and coherent_context.strip():
        parts.append(
            "\n=== Coherent Clip & Sequential Context ===\n"
            + coherent_context.strip()
            + "\n==========================================="
        )

    if prompt_guidance and prompt_guidance.strip():
        parts.append(
            "\n=== User Guidance & Specific Focus Instructions ===\n"
            + prompt_guidance.strip()
            + "\n\n(Important: Please prioritize identifying these specific individuals, locations, actions, and visual cues in the title, summary, people_or_subjects, tags, and events when observed.)"
            + "\n===================================================="
        )

    if slug_guidance and slug_guidance.strip():
        parts.append(
            "\n=== AI Suggested Slug & Filename Naming Convention ===\n"
            + "Strict instruction for generating 'suggested_filename':\n"
            + slug_guidance.strip()
            + "\n(Make sure 'suggested_filename' strictly follows this naming convention, using lowercase and underscores, without file extension or date prefix unless explicitly specified.)"
            + "\n======================================================="
        )

    parts.append("\nPlease output the JSON analysis according to the specified schema.")
    return "\n".join(parts)

def parse_ai_response(raw_text: str, default_title: str = "Home Video") -> VideoAnalysisResult:
    """Safely extract JSON or parse line-by-line fallback from AI output."""
    clean_text = raw_text.strip()
    
    # Try finding JSON block inside ```json ... ``` or first { to last }
    json_candidate = clean_text
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', clean_text, re.DOTALL)
    if match:
        json_candidate = match.group(1)
    else:
        first_brace = clean_text.find('{')
        last_brace = clean_text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_candidate = clean_text[first_brace:last_brace + 1]

    try:
        data = json.loads(json_candidate)
        events = []
        for ev in data.get("events", []):
            if isinstance(ev, dict) and "timecode" in ev:
                events.append(TimestampEvent(
                    timecode=str(ev.get("timecode", "00:00")),
                    description=str(ev.get("description", "")),
                    is_highlight=bool(ev.get("is_highlight", False))
                ))
            elif isinstance(ev, str):
                # E.g. "00:15 - Subject walks in"
                events.append(TimestampEvent(timecode="00:00", description=ev))

        tags = data.get("tags", [])
        animals = data.get("animals_or_pets", [])
        objects = data.get("objects", [])

        # Automatically merge recognizable animals and objects into tags if not already present
        for item in animals + objects:
            if item and item.lower() not in [t.lower() for t in tags]:
                tags.append(item.lower())

        detected_date_in_ctx = data.get("detected_date_in_context") or data.get("detected_date") or None
        detected_date_evid = data.get("detected_date_evidence") or data.get("date_evidence") or None

        raw_title = str(data.get("title", default_title)).strip()
        clean_title = raw_title
        for _ in range(3):
            clean_title = clean_title.strip("\"'`«»“” \t\n")
            clean_title = re.sub(r'[\s:;,-]+$', '', clean_title).strip()
        if not clean_title:
            clean_title = default_title

        raw_slug = str(data.get("suggested_filename", "")).strip()
        for _ in range(3):
            raw_slug = raw_slug.strip("\"'`«»“” \t\n")
            raw_slug = re.sub(r'[\s:;,-]+$', '', raw_slug).strip()
        clean_slug = raw_slug.replace(" ", "_")

        return VideoAnalysisResult(
            title=clean_title,
            summary=data.get("summary", clean_text[:300]),
            events=events,
            tags=tags,
            people_or_subjects=data.get("people_or_subjects", []),
            animals_or_pets=animals,
            objects=objects,
            suggested_filename=clean_slug,
            detected_date_in_context=str(detected_date_in_ctx).strip() if detected_date_in_ctx else None,
            detected_date_evidence=str(detected_date_evid).strip() if detected_date_evid else None,
            raw_response=raw_text
        )
    except Exception:
        # Fallback parser for non-JSON model output
        lines = clean_text.splitlines()
        first_line = lines[0].strip().strip("\"'`«»“”") if lines else default_title
        if len(first_line) > 60:
            last_space = first_line[:60].rfind(" ")
            title = first_line[:last_space].strip() if last_space > 10 else first_line[:60].strip()
        else:
            title = first_line
        title = re.sub(r'[\s:;,-]+$', '', title).strip() or default_title
        events: List[TimestampEvent] = []
        for line in lines:
            ts_match = re.match(r'^(?:★\s*)?(\d{1,2}:\d{2}(?::\d{2})?)\s*[-—:]?\s*(.*)', line.strip())
            if ts_match:
                is_star = "★" in line
                events.append(TimestampEvent(
                    timecode=ts_match.group(1),
                    description=ts_match.group(2).strip(),
                    is_highlight=is_star
                ))

        return VideoAnalysisResult(
            title=title,
            summary=clean_text,
            events=events,
            tags=[],
            people_or_subjects=[],
            animals_or_pets=[],
            objects=[],
            suggested_filename="",
            raw_response=raw_text
        )

parse_analysis_response = parse_ai_response
