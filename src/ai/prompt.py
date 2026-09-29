import json
import re
from typing import Dict, Any, List, Optional
from src.ai.base import VideoAnalysisResult, TimestampEvent

SYSTEM_PROMPT = """You are an expert video archivist and editor assistant analyzing footage from private and home video collections.
Analyze the provided sequential video frames and audio transcript to understand the content of the clip.

You must respond in valid JSON with the following structure:
{
  "title": "Brief descriptive title (3-7 words, e.g. Kids Playing Tennis in the Backyard)",
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
  "suggested_filename": "kids_playing_tennis_backyard"
}

Important Rules:
1. Ground your descriptions strictly on what is visible in the frames and heard in the audio.
2. If animals or pets (especially dogs or cats) are present, list them in "animals_or_pets" with specific breed or type whenever identifiable (e.g. "Golden Retriever", "Beagle", "Bulldog", "Pug", "Tabby Cat").
3. In "objects", list prominent physical items, sports gear, equipment, instruments, tools, or vehicles (e.g. "tennis racket", "acoustic guitar", "bicycle", "skateboard", "camera").
4. If key moments stand out as memorable or exciting, set "is_highlight": true.
5. Keep the suggested_filename lowercase with underscores, without extension or dates.
6. Output ONLY the raw JSON object, without introductory text or markdown formatting if possible.
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
    prompt_guidance: Optional[str] = None
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

    if prompt_guidance and prompt_guidance.strip():
        parts.append(
            "\n=== User Guidance & Specific Focus Instructions ===\n"
            + prompt_guidance.strip()
            + "\n\n(Important: Please prioritize identifying these specific individuals, locations, actions, and visual cues in the title, summary, people_or_subjects, tags, and events when observed.)"
            + "\n===================================================="
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

        return VideoAnalysisResult(
            title=data.get("title", default_title),
            summary=data.get("summary", clean_text[:300]),
            events=events,
            tags=tags,
            people_or_subjects=data.get("people_or_subjects", []),
            animals_or_pets=animals,
            objects=objects,
            suggested_filename=data.get("suggested_filename", ""),
            raw_response=raw_text
        )
    except Exception:
        # Fallback parser for non-JSON model output
        lines = clean_text.splitlines()
        title = lines[0][:60] if lines else default_title
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
