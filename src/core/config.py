import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ValidationError

from src.core.paths import get_config_path, get_app_root

logger = logging.getLogger(__name__)

class AppConfig(BaseModel):
    # System Binaries
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None

    # AI Vision & Reasoning
    vision_provider: str = Field(default="ollama", description="ollama | openai_compatible | cloud")
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.2-vision")
    ollama_num_ctx: int = Field(default=16384, description="Context window size (num_ctx) in tokens for Ollama (e.g. 8192, 16384, 32768, 65536, or 0 for auto). Default 16384 prevents context overflow on multimodal video analysis.")
    
    openai_compatible_url: str = Field(default="http://localhost:1234/v1")
    openai_compatible_api_key: str = Field(default="lm-studio")
    openai_compatible_model: str = Field(default="local-model")
    
    cloud_provider: str = Field(default="gemini", description="gemini | openai | anthropic | openrouter | custom_openai")
    cloud_model: str = Field(default="gemini-2.5-flash", description="Model identifier for cloud vision & LLM inference")
    cloud_endpoint: Optional[str] = Field(default="", description="Custom OpenAI-standard API base URL (e.g. https://openrouter.ai/api/v1 or https://api.groq.com/openai/v1)")
    api_keys: Dict[str, str] = Field(default_factory=lambda: {
        "gemini": "",
        "openai": "",
        "anthropic": "",
        "openrouter": "",
        "custom": ""
    })

    # AI Prompt Guidance & Description Tuning
    ai_timeout_seconds: int = Field(default=600, description="HTTP request timeout in seconds for VLM inference (e.g. 600s = 10 minutes for large 27B+ models).")
    custom_system_prompt: Optional[str] = Field(default=None, description="Custom system prompt override (None uses default)")
    default_prompt_guidance: str = Field(default="", description="Permanent guidance addendum included in all video descriptions (e.g. key family names, locations, tone)")
    batch_prompt_guidance: str = Field(default="", description="Active batch guidance prompt for current queue processing")
    default_slug_guidance: str = Field(default="", description="Permanent naming convention guidance for AI suggested slug (e.g. category_action_detail, max 30 chars, lowercase underscores)")
    batch_slug_guidance: str = Field(default="", description="Active batch naming convention guidance for AI suggested slug")
    use_filename_context: bool = Field(default=True, description="Incorporate clues from original filename (dates, names, event keywords) into AI analysis and suggested slug")
    filename_date_order: str = Field(default="auto", description="Date order preference in filenames: auto | ymd | mdy | dmy")

    # Whisper Audio Transcription & Subtitles
    transcribe_audio: bool = True
    whisper_backend: str = Field(default="faster-whisper", description="faster-whisper | openai-whisper | remote | none")
    whisper_model: str = Field(default="base")
    whisper_remote_url: Optional[str] = None
    whisper_api_key: Optional[str] = Field(default="", description="API key or Bearer token for remote Whisper server")
    whisper_language: Optional[str] = None
    whisper_translate_to_english: bool = Field(default=False, description="Translate foreign language speech to English during Whisper transcription")
    whisper_task: str = Field(default="transcribe", description="Whisper task: 'transcribe' (keep original language) or 'translate' (translate to English)")
    whisper_device: str = Field(default="auto", description="auto | cuda | cpu")
    whisper_device_index: int = Field(default=0, description="NVIDIA GPU device index (0 for first GPU, 1 for second, etc.)")
    whisper_compute_type: str = Field(default="auto", description="auto | float16 | int8 | int8_float16 | float32")

    # Subtitle Ingestion & Context
    use_subtitles: bool = Field(default=True, description="Use accompanying .srt or embedded subtitles as AI context")
    prefer_subtitles_over_whisper: bool = Field(default=True, description="If subtitles exist, use them and skip running Whisper")
    full_transcription_if_no_subtitles: bool = Field(default=True, description="Fallback to full Whisper audio transcription when no subtitles exist")

    # Pipeline Concurrency Mode
    processing_execution_mode: str = Field(default="serial", description="serial | concurrent")

    # Sampling & Long Video Settings
    sampling_strategy: str = Field(default="interval", description="interval | key_moments | scene_change")
    sampling_interval_seconds: int = Field(default=60, description="Interval in seconds between frames for long videos (e.g. 30, 60, 120, 300, 600)")
    periodic_interval_seconds: int = 10  # Legacy compatibility
    max_frames_per_video: int = Field(default=30, description="Maximum frames extracted across video to prevent VLM context overload")
    key_moments_count: int = Field(default=20, description="Number of milestone moments to capture when sampling key moments")
    frame_max_dimension: int = 768
    temp_retention_policy: str = Field(
        default="immediate",
        description="immediate | 1_day | 7_days | 30_days | persistent"
    )


    # Facial Recognition (Hybrid: Built-in local ONNX or CompreFace / Immich)
    face_recognition_enabled: bool = True
    face_provider: str = Field(default="builtin", description="builtin | compreface")
    face_detection_confidence: float = Field(default=0.70, description="Minimum detection confidence threshold (0.30 - 0.95). Higher strictly rejects hands/elbows.")
    face_max_distance: float = Field(default=0.45, description="Maximum recognition distance (0.20 strict to 0.95 permissive). Higher values increase coherence for varied angles/lighting of the same person.")
    face_match_threshold: float = Field(default=0.55, description="Cosine similarity threshold for clustering faces into person identities (1.0 - max_distance)")
    compreface_url: str = Field(default="http://localhost:8000")
    compreface_api_key: str = Field(default="")

    # Sidecar & Metadata Export Standards
    metadata_preset: str = Field(default="all", description="all | jellyfin | digikam | custom")
    export_txt: bool = True
    export_info_json: bool = True
    export_xmp: bool = True
    export_nfo: bool = True
    export_edl: bool = False
    export_fcpxml: bool = False
    export_srt: bool = Field(default=True, description="Auto-export full dialogue subtitle (.srt) sidecar if not already available")

    # Safe Renaming & Organization
    rename_template: str = "{date_compact}_{time_zulu}_{title}"
    rename_scheme: str = Field(default="compact_zulu_title", description="compact_zulu_title | compact_zulu_names_title | compact_time_title | compact_dashed_time_title | compact_date_title | date_title | date_time_title | title_only | original_title | ai_slug | custom")
    auto_rename: bool = False
    max_title_length: int = Field(default=50, description="Maximum character length for AI title in filenames (0 for unlimited)")
    include_names_in_title: bool = Field(default=False, description="Automatically prepend/include recognized person names in titles")
    rename_time_format: str = Field(default="zulu_compact", description="zulu_compact | zulu_dashed | local_compact | local_dashed")
    date_source: str = Field(default="smart", description="smart | filename | metadata")
    default_date_override: Optional[str] = Field(default=None, description="Optional manual batch date override (YYYY-MM-DD or ISO timestamp)")
    detected_date_action: str = Field(default="ask", description="How to handle date/time found in filename or visual video context: 'ask' (request operator confirmation) | 'auto' (automatically update recorded date and filenames) | 'ignore' (keep original metadata)")
    sync_file_mtime_with_date: bool = Field(default=True, description="When date is updated, synchronize filesystem modification time (mtime)")

    # In-file Tagging (Safe Mode)
    enable_in_file_tagging: bool = False
    backup_before_tagging: bool = True
    flush_backup_on_success: bool = Field(default=True, description="Automatically flush/delete the .bak file after successful in-file tagging and stream integrity verification.")
    verify_integrity: bool = True

    # Web Server & Access Control
    host: str = Field(default="127.0.0.1", description="Bind address. 127.0.0.1 = this computer only; 0.0.0.0 = whole LAN (an access token is then required).")
    port: int = 5555
    access_token: str = Field(default="", description="Shared secret required for API/UI access when the server is bound to a non-loopback address. Auto-generated on first LAN start.")
    cors_allowed_origins: List[str] = Field(default_factory=list, description="Extra browser origins allowed to call the API cross-origin (same-origin never needs this).")


# --- Secret handling -------------------------------------------------------

SECRET_MASK = "********"
SECRET_FIELDS = ("openai_compatible_api_key", "whisper_api_key", "compreface_api_key")
# Fields that may never be changed through the HTTP API (only via config file / env).
API_READONLY_FIELDS = ("access_token",)
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def is_loopback_host(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def mask_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of a config dict with every secret replaced by SECRET_MASK (empty stays empty)."""
    out = dict(data)
    for field in SECRET_FIELDS:
        if out.get(field):
            out[field] = SECRET_MASK
    if isinstance(out.get("api_keys"), dict):
        out["api_keys"] = {k: (SECRET_MASK if v else v) for k, v in out["api_keys"].items()}
    if out.get("access_token"):
        out["access_token"] = SECRET_MASK
    return out


def resolve_secret(value: Optional[str], stored: Optional[str]) -> Optional[str]:
    """If a client echoes back the mask, substitute the stored secret."""
    if value == SECRET_MASK:
        return stored
    return value


def apply_config_update(current: AppConfig, update: Dict[str, Any]) -> AppConfig:
    """
    Validate and apply a partial config update.

    Unlike ``model_copy(update=...)`` this runs full pydantic validation (raising
    ``pydantic.ValidationError`` on bad types), ignores unknown keys, keeps stored
    secrets when the client sends the mask back, and refuses to change read-only fields.
    """
    merged = current.model_dump()
    for key, value in (update or {}).items():
        if key not in AppConfig.model_fields or key in API_READONLY_FIELDS:
            continue
        if key in SECRET_FIELDS:
            value = resolve_secret(value, merged.get(key))
        elif key == "api_keys" and isinstance(value, dict):
            old_keys = merged.get("api_keys") or {}
            value = {k: resolve_secret(v, old_keys.get(k)) for k, v in value.items()}
        merged[key] = value
    return AppConfig.model_validate(merged)


# --- Persistence -----------------------------------------------------------

def _backup_corrupt_config(config_file: Path) -> None:
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = config_file.with_name(f"{config_file.name}.corrupt-{stamp}")
        shutil.copy2(config_file, backup)
        logger.error(f"Backed up unreadable/invalid config to {backup}")
    except Exception as exc:
        logger.warning(f"Could not back up invalid config: {exc}", exc_info=True)


def load_config() -> AppConfig:
    """
    Load configuration, or create defaults.

    If the file has some invalid values, only those fields fall back to their
    defaults (the rest of the user's settings are kept) and the original file is
    backed up first, instead of silently resetting everything.
    """
    config_file = get_config_path()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("config root must be a JSON object")
        except Exception as e:
            logger.error(f"Error reading config at {config_file}: {e}. Using defaults.", exc_info=True)
            _backup_corrupt_config(config_file)
            config = AppConfig()
            save_config(config)
            return config

        try:
            return AppConfig(**data)
        except ValidationError as e:
            _backup_corrupt_config(config_file)
            bad = {err["loc"][0] for err in e.errors() if err.get("loc")}
            logger.error(f"Invalid config values for {sorted(map(str, bad))}; reverting only those to defaults.")
            cleaned = {k: v for k, v in data.items() if k not in bad}
            config = AppConfig(**cleaned)
            save_config(config)
            return config

    config = AppConfig()
    save_config(config)
    return config


def save_config(config: AppConfig) -> None:
    """Persist configuration atomically (write temp file, then replace)."""
    config_file = get_config_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = config_file.with_name(config_file.name + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)
    os.replace(tmp_file, config_file)
