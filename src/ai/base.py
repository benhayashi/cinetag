from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class FrameItem(BaseModel):
    path: str
    timestamp_seconds: float
    timecode: str

class TimestampEvent(BaseModel):
    timecode: str
    description: str
    is_highlight: bool = False

class VideoAnalysisResult(BaseModel):
    title: str = Field(description="Short descriptive title for the video")
    summary: str = Field(description="Comprehensive summary of what happens in the video")
    events: List[TimestampEvent] = Field(default_factory=list, description="Timestamped events")
    tags: List[str] = Field(default_factory=list, description="Categorization and search tags")
    people_or_subjects: List[str] = Field(default_factory=list, description="Detected people or subjects")
    animals_or_pets: List[str] = Field(default_factory=list, description="Detected animals, dogs, cats, or pets (with breed if recognizable)")
    objects: List[str] = Field(default_factory=list, description="Prominent physical objects, tools, sports gear, equipment, vehicles, instruments")
    suggested_filename: str = Field(default="", description="Safe slugified filename recommendation")
    audio_transcript: Optional[str] = None
    provider_name: str = ""
    model_name: str = ""
    raw_response: Optional[str] = None

class BaseVisionProvider(ABC):
    """Abstract interface for all Vision & Language Model backends."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend endpoint is reachable."""
        pass

    @abstractmethod
    def list_models(self) -> List[str]:
        """List available vision models at the provider endpoint."""
        pass

    @abstractmethod
    def describe_video(
        self,
        frames: List[FrameItem],
        audio_transcript: Optional[str] = None,
        context_prompt: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_guidance: Optional[str] = None
    ) -> VideoAnalysisResult:
        """Analyze sampled video frames and optional audio transcript."""
        pass

