import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

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
    
    openai_compatible_url: str = Field(default="http://localhost:1234/v1")
    openai_compatible_api_key: str = Field(default="lm-studio")
    openai_compatible_model: str = Field(default="local-model")
    
    cloud_provider: str = Field(default="gemini", description="gemini | anthropic | openai")
    api_keys: Dict[str, str] = Field(default_factory=lambda: {
        "gemini": "",
        "anthropic": "",
        "openai": ""
    })

    # AI Prompt Guidance & Description Tuning
    custom_system_prompt: Optional[str] = Field(default=None, description="Custom system prompt override (None uses default)")
    default_prompt_guidance: str = Field(default="", description="Permanent guidance addendum included in all video descriptions (e.g. key family names, locations, tone)")
    batch_prompt_guidance: str = Field(default="", description="Active batch guidance prompt for current queue processing")

    # Whisper Audio Transcription & Subtitles
    transcribe_audio: bool = True
    whisper_backend: str = Field(default="faster-whisper", description="faster-whisper | openai-whisper | remote | none")
    whisper_model: str = Field(default="base")
    whisper_remote_url: Optional[str] = None
    whisper_api_key: Optional[str] = Field(default="", description="API key or Bearer token for remote Whisper server")
    whisper_language: Optional[str] = None

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

    # In-file Tagging (Safe Mode)
    enable_in_file_tagging: bool = False
    backup_before_tagging: bool = True
    verify_integrity: bool = True

    # Web Server
    host: str = "0.0.0.0"
    port: int = 5555

def load_config() -> AppConfig:
    """Load configuration from config path or create defaults."""
    config_file = get_config_path()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return AppConfig(**data)
        except Exception as e:
            logger.error(f"Error reading config at {config_file}: {e}. Using defaults.")

    config = AppConfig()
    save_config(config)
    return config

def save_config(config: AppConfig) -> None:
    """Persist configuration to file."""
    config_file = get_config_path()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)
