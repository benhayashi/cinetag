import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from src.core.config import AppConfig, load_config
from src.core.privacy import cleanup_video_cache, purge_expired_cache
from src.media.probe import probe_video
from src.media.sampler import extract_frames, extract_audio
from src.media.tagger import apply_metadata_tags, flush_orphaned_backups
from src.media.renamer import generate_suggested_name, execute_rename
from src.ai.base import VideoAnalysisResult
from src.ai.ollama_provider import OllamaVisionProvider
from src.ai.openai_provider import OpenAICompatibleVisionProvider
from src.ai.whisper_service import WhisperTranscriptionService
from src.ai.cloud_provider import CloudVisionProvider
from src.exporters.sidecars import write_txt_sidecar, write_info_json_sidecar, write_xmp_sidecar
from src.exporters.nle import write_edl_markers
from src.exporters.nfo import write_nfo_sidecar
from src.media.faces import process_video_faces

logger = logging.getLogger(__name__)

class TaskItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    file_path: str
    filename: str
    status: str = "queued"  # queued, processing, completed, failed, cancelled
    stage: str = "In queue"
    progress: int = 0
    conflict_mode: str = "overwrite"  # overwrite | enumerate
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    date_override: Optional[str] = None
    date_source: Optional[str] = None
    prompt_guidance: Optional[str] = None

class QueueManager:
    """Manages background batch processing queue and worker thread."""

    def __init__(self):
        self.queue: List[TaskItem] = []
        self.current_task: Optional[TaskItem] = None
        self.is_running: bool = False
        self.is_paused: bool = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.logs: List[Dict[str, Any]] = []

    def log(self, message: str, level: str = "info", task_id: Optional[str] = None):
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "task_id": task_id
        }
        self.logs.append(entry)
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

    def add_to_queue(
        self,
        file_paths: List[str],
        conflict_mode: str = "overwrite",
        date_override: Optional[str] = None,
        date_source: Optional[str] = None,
        prompt_guidance: Optional[str] = None
    ) -> List[TaskItem]:
        with self._lock:
            added = []
            active_paths = {t.file_path for t in self.queue if t.status in ("queued", "processing")}
            for p_str in file_paths:
                p = Path(p_str)
                resolved_str = str(p.resolve())
                if p.exists() and resolved_str not in active_paths:
                    # Remove older completed/failed record so clip can be reprocessed cleanly
                    self.queue = [t for t in self.queue if t.file_path != resolved_str]
                    task = TaskItem(
                        file_path=resolved_str,
                        filename=p.name,
                        conflict_mode=conflict_mode,
                        date_override=date_override,
                        date_source=date_source,
                        prompt_guidance=prompt_guidance
                    )
                    self.queue.append(task)
                    added.append(task)
            self.log(f"Added {len(added)} files to queue (conflict mode: {conflict_mode}).")
            return added

    def start(self):
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                self.is_paused = False
                return
            self.is_running = True
            self.is_paused = False
            self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._worker_thread.start()
            self.log("Worker queue started.")

    def pause(self):
        with self._lock:
            self.is_paused = True
            self.log("Worker queue paused.")

    def clear(self):
        with self._lock:
            # Keep currently processing, clear pending
            if self.current_task and self.current_task.status == "processing":
                self.queue = [self.current_task]
            else:
                self.queue = []
            self.log("Queue cleared.")

    def clear_completed(self) -> int:
        with self._lock:
            initial = len(self.queue)
            completed_tasks = [t for t in self.queue if t.status == "completed"]
            self.queue = [t for t in self.queue if t.status != "completed"]
            removed = initial - len(self.queue)
            for t in completed_tasks:
                try:
                    p = Path(t.file_path)
                    flush_orphaned_backups(p)
                except Exception:
                    pass
            self.log(f"Cleared {removed} completed task(s) from queue.")
            return removed

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self.queue)
            completed = sum(1 for t in self.queue if t.status == "completed")
            failed = sum(1 for t in self.queue if t.status == "failed")
            queued = sum(1 for t in self.queue if t.status == "queued")
            processing = sum(1 for t in self.queue if t.status == "processing")

            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "counts": {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "queued": queued,
                    "processing": processing
                },
                "current_task": self.current_task.model_dump() if self.current_task else None,
                "tasks": [t.model_dump() for t in self.queue],
                "recent_logs": self.logs[-50:]
            }

    def _run_loop(self):
        while self.is_running:
            if self.is_paused:
                time.sleep(0.5)
                continue

            task_to_run = None
            with self._lock:
                for t in self.queue:
                    if t.status == "queued":
                        task_to_run = t
                        break

            if not task_to_run:
                with self._lock:
                    self.current_task = None
                time.sleep(1.0)
                continue

            self._process_single_task(task_to_run)

    def _process_single_task(self, task: TaskItem):
        with self._lock:
            self.current_task = task
            task.status = "processing"
            task.started_at = datetime.now().isoformat()
            task.progress = 5
            task.stage = "Probing video"

        video_path = Path(task.file_path)
        self.log(f"Beginning analysis of {video_path.name}", task_id=task.id)

        try:
            cfg = load_config()

            # 1. Probe video
            meta = probe_video(video_path, custom_ffprobe=cfg.ffprobe_path)

            # Date extraction & resolution (smart fallback, filename date extraction, or batch override)
            from src.media.renamer import resolve_datetime
            date_override_val = task.date_override or getattr(cfg, "default_date_override", None)
            date_source_val = task.date_source or getattr(cfg, "date_source", "smart")
            dt_local, dt_utc, date_source_used = resolve_datetime(
                original_path=video_path,
                creation_date=meta.get("creation_time"),
                date_override=date_override_val,
                date_source=date_source_val,
                original_filename=task.filename
            )
            resolved_iso = dt_local.isoformat()
            if date_source_used in ("override", "filename") or not meta.get("creation_time"):
                meta["creation_time"] = resolved_iso
                meta["date_source_used"] = date_source_used
                self.log(f"Determined video date for {video_path.name}: {resolved_iso} (source: {date_source_used})", task_id=task.id)

            task.progress = 15
            task.stage = "Checking subtitles & audio"

            # Subtitle check (.srt or embedded)
            from src.media.subtitles import get_video_subtitles
            subtitle_info = get_video_subtitles(video_path, custom_ffmpeg=cfg.ffmpeg_path)
            subtitles_found = subtitle_info.get("has_subtitles", False)
            sub_source = subtitle_info.get("source", "none")
            subtitle_dialogue = subtitle_info.get("dialogue_text") if cfg.use_subtitles else None

            if subtitles_found and cfg.use_subtitles:
                self.log(f"Found {sub_source} subtitles for {video_path.name}", task_id=task.id)

            # Determine whether Whisper is needed
            need_whisper = False
            if cfg.transcribe_audio and meta.get("has_audio", True):
                if not subtitles_found or not cfg.prefer_subtitles_over_whisper:
                    need_whisper = True
                elif not subtitles_found and cfg.full_transcription_if_no_subtitles:
                    need_whisper = True

            transcript = None
            transcript_segments = []
            frames_raw = []

            def do_audio_transcription():
                nonlocal transcript, transcript_segments
                if not need_whisper:
                    return
                try:
                    self.log(f"Extracting audio for {video_path.name}...", task_id=task.id)
                    wav_path = extract_audio(video_path, custom_ffmpeg=cfg.ffmpeg_path)
                    if wav_path:
                        whisper_svc = WhisperTranscriptionService(
                            backend=cfg.whisper_backend,
                            model_name=cfg.whisper_model,
                            device=getattr(cfg, "whisper_device", "auto"),
                            compute_type=getattr(cfg, "whisper_compute_type", "auto"),
                            remote_url=cfg.whisper_remote_url,
                            language=cfg.whisper_language,
                            api_key=getattr(cfg, "whisper_api_key", None)
                        )
                        avail = whisper_svc.is_available()
                        if cfg.whisper_backend == "faster-whisper" and not avail.get("faster_whisper"):
                            self.log("⚠️ Local Whisper engine (faster-whisper) is not installed in the Python environment. Audio transcription skipped. (You can install it in Settings > Audio & Whisper).", level="warning", task_id=task.id)
                            return
                        elif cfg.whisper_backend == "openai-whisper" and not avail.get("openai_whisper"):
                            self.log("⚠️ openai-whisper library is not installed in Python. Audio transcription skipped.", level="warning", task_id=task.id)
                            return

                        det_res = whisper_svc.transcribe_detailed(
                            wav_path,
                            log_callback=lambda msg, level="info": self.log(msg, level=level, task_id=task.id)
                        )
                        transcript = det_res.get("text")
                        transcript_segments = det_res.get("segments", [])
                        if det_res.get("error"):
                            self.log(f"⚠️ Whisper error details: {det_res['error']}", level="warning", task_id=task.id)

                        if transcript:
                            self.log(f"Audio transcription complete: \"{transcript[:80]}...\"", task_id=task.id)
                        elif not det_res.get("error"):
                            self.log("Whisper finished: No spoken dialogue detected in audio clip.", task_id=task.id)
                except Exception as e:
                    self.log(f"Audio transcription note for {video_path.name}: {e}", level="warning", task_id=task.id)

            def do_frame_extraction():
                nonlocal frames_raw
                self.log(f"Extracting frames for {video_path.name} (strategy={cfg.sampling_strategy})...", task_id=task.id)
                interval_secs = getattr(cfg, "sampling_interval_seconds", cfg.periodic_interval_seconds)
                frames_raw = extract_frames(
                    video_path,
                    interval_seconds=interval_secs,
                    max_frames=cfg.max_frames_per_video,
                    max_dimension=cfg.frame_max_dimension,
                    strategy=cfg.sampling_strategy,
                    key_moments_count=getattr(cfg, "key_moments_count", 20),
                    custom_ffmpeg=cfg.ffmpeg_path
                )

            # Pipeline execution: Serial vs Concurrent
            if cfg.processing_execution_mode == "concurrent" and need_whisper:
                task.stage = "Concurrent extraction (audio & frames)"
                task.progress = 25
                self.log("Running audio transcription and frame extraction concurrently...", task_id=task.id)
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=2) as executor:
                    f_audio = executor.submit(do_audio_transcription)
                    f_frames = executor.submit(do_frame_extraction)
                    f_audio.result()
                    f_frames.result()
            else:
                # Serial execution (safe default for local hardware)
                if need_whisper:
                    task.stage = "Transcribing audio"
                    task.progress = 25
                    do_audio_transcription()
                elif subtitles_found and cfg.use_subtitles:
                    self.log(f"Using {sub_source} subtitles directly for context (skipped Whisper).", task_id=task.id)
                    transcript = subtitle_dialogue

                task.stage = "Extracting frames"
                task.progress = 45
                do_frame_extraction()

            # If transcript wasn't generated by Whisper but subtitles exist, use subtitles as transcript
            if not transcript and subtitle_dialogue:
                transcript = subtitle_dialogue

            if not frames_raw:
                raise RuntimeError(f"No frames could be extracted from {video_path.name}")

            from src.ai.base import FrameItem
            frames = [FrameItem(**f) for f in frames_raw]
            self.log(f"Extracted {len(frames)} frames from {video_path.name}", task_id=task.id)

            # 4. Vision & Reasoning
            task.stage = "AI Vision & Reasoning"
            task.progress = 60
            self.log(f"Sending {len(frames)} frames to {cfg.vision_provider}...", task_id=task.id)

            # Context prompt contains subtitle markers if both exist
            extra_ctx = None
            if subtitle_dialogue and transcript and transcript != subtitle_dialogue:
                extra_ctx = f"Subtitles:\n{subtitle_dialogue}"

            # Combine guidance: task prompt guidance or batch guidance + default guidance
            guidance_notes = []
            if cfg.default_prompt_guidance and cfg.default_prompt_guidance.strip():
                guidance_notes.append(cfg.default_prompt_guidance.strip())
            active_batch_guidance = (task.prompt_guidance or cfg.batch_prompt_guidance or "").strip()
            if active_batch_guidance and active_batch_guidance not in guidance_notes:
                guidance_notes.append(active_batch_guidance)

            combined_guidance = "\n\n".join(guidance_notes) if guidance_notes else None
            if combined_guidance:
                short_note = combined_guidance.replace("\n", " ")
                if len(short_note) > 60:
                    short_note = short_note[:57] + "..."
                self.log(f"Applying AI guidance focus: \"{short_note}\"", task_id=task.id)

            timeout_sec = getattr(cfg, "ai_timeout_seconds", 600)
            analysis: VideoAnalysisResult
            if cfg.vision_provider == "ollama":
                ollama_ctx = getattr(cfg, "ollama_num_ctx", 16384)
                provider = OllamaVisionProvider(
                    base_url=cfg.ollama_url,
                    default_model=cfg.ollama_model,
                    default_num_ctx=ollama_ctx
                )
                analysis = provider.describe_video(
                    frames,
                    audio_transcript=transcript,
                    context_prompt=extra_ctx,
                    system_prompt=cfg.custom_system_prompt,
                    prompt_guidance=combined_guidance,
                    timeout_seconds=timeout_sec,
                    num_ctx=ollama_ctx
                )
            elif cfg.vision_provider == "openai_compatible":
                provider = OpenAICompatibleVisionProvider(
                    base_url=cfg.openai_compatible_url,
                    api_key=cfg.openai_compatible_api_key,
                    default_model=cfg.openai_compatible_model
                )
                analysis = provider.describe_video(
                    frames,
                    audio_transcript=transcript,
                    context_prompt=extra_ctx,
                    system_prompt=cfg.custom_system_prompt,
                    prompt_guidance=combined_guidance,
                    timeout_seconds=timeout_sec
                )
            elif cfg.vision_provider == "cloud":
                provider = CloudVisionProvider(
                    provider=cfg.cloud_provider,
                    api_keys=cfg.api_keys
                )
                analysis = provider.describe_video(
                    frames,
                    audio_transcript=transcript,
                    context_prompt=extra_ctx,
                    system_prompt=cfg.custom_system_prompt,
                    prompt_guidance=combined_guidance,
                    timeout_seconds=timeout_sec
                )
            else:
                raise ValueError(f"Unknown vision provider: {cfg.vision_provider}")

            # Clean and normalize any AI-generated people/subject names (e.g. "man/father 'Ben'" -> "Ben")
            if analysis.people_or_subjects:
                from src.media.faces import clean_person_name
                cleaned_people = []
                for p in analysis.people_or_subjects:
                    clean_p = clean_person_name(p)
                    if clean_p and clean_p not in cleaned_people:
                        cleaned_people.append(clean_p)
                analysis.people_or_subjects = cleaned_people

            # 4b. Facial Recognition (Hybrid: Built-in local or CompreFace)
            if cfg.face_recognition_enabled:
                task.stage = "Facial recognition"
                task.progress = 75
                self.log(f"Scanning for faces ({cfg.face_provider})...", task_id=task.id)
                try:
                    detected_faces = process_video_faces(frames, cfg, video_path)
                    if detected_faces:
                        from src.media.faces import face_registry
                        detected_pids = [f.get("person_id") or f.get("id") for f in detected_faces if (f.get("person_id") or f.get("id"))]
                        guessed = face_registry.correlate_and_guess_names(
                            detected_face_ids=detected_pids,
                            ai_people_names=analysis.people_or_subjects,
                            video_path=str(video_path.resolve()),
                            summary=analysis.summary
                        )
                        for g in guessed:
                            self.log(f"🤖 AI Face Match: Inferred identity for {g['old_name']} -> {g['new_name']}", task_id=task.id)
                            for f in detected_faces:
                                if f.get("person_id") == g["person_id"] or f.get("id") == g["person_id"]:
                                    f["name"] = g["new_name"]
                            if g["old_name"] in analysis.people_or_subjects:
                                analysis.people_or_subjects = [g["new_name"] if p == g["old_name"] else p for p in analysis.people_or_subjects]

                        for face_info in detected_faces:
                            fname = face_info["name"]
                            if fname not in analysis.people_or_subjects:
                                analysis.people_or_subjects.append(fname)
                        names_str = ", ".join(f["name"] for f in detected_faces)
                        self.log(f"Identified {len(detected_faces)} person(s): {names_str}", task_id=task.id)

                    # Ensure people/subjects detected from analysis are registered in internal face database
                    all_frame_paths = [Path(f.path if hasattr(f, "path") else f["path"]) for f in frames if (hasattr(f, "path") or "path" in f)]
                    first_frame_path = all_frame_paths[0] if all_frame_paths else None
                    from src.media.faces import face_registry
                    for subj in analysis.people_or_subjects:
                        face_registry.register_named_subject(
                            name=subj,
                            video_path=str(video_path.resolve()),
                            frame_path=first_frame_path,
                            candidate_frames=all_frame_paths
                        )
                except Exception as fe:
                    self.log(f"Facial recognition note: {fe}", level="warning", task_id=task.id)

            # 5. Export sidecars
            task.stage = "Writing sidecars"
            task.progress = 85
            written_sidecars = []

            if cfg.export_txt:
                txt_p = write_txt_sidecar(video_path, analysis, meta, conflict_mode=task.conflict_mode)
                written_sidecars.append(str(txt_p))
            if cfg.export_info_json:
                json_p = write_info_json_sidecar(video_path, analysis, meta, conflict_mode=task.conflict_mode)
                written_sidecars.append(str(json_p))
            if cfg.export_xmp:
                xmp_p = write_xmp_sidecar(video_path, analysis, meta, conflict_mode=task.conflict_mode)
                written_sidecars.append(str(xmp_p))
            if cfg.export_nfo:
                nfo_p = write_nfo_sidecar(video_path, analysis, meta, conflict_mode=task.conflict_mode)
                written_sidecars.append(str(nfo_p))
            if cfg.export_edl and analysis.events:
                edl_p = write_edl_markers(video_path, analysis.events, conflict_mode=task.conflict_mode)
                written_sidecars.append(str(edl_p))

            # Auto-export full dialogue or visual events .srt subtitle sidecar
            if getattr(cfg, "export_srt", True):
                from src.media.subtitles import generate_srt_from_text, generate_srt_from_events, write_srt_sidecar
                raw_text = transcript or subtitle_dialogue or ""
                srt_body = ""
                if raw_text.strip():
                    srt_body = generate_srt_from_text(
                        text=raw_text,
                        total_duration=meta.get("duration"),
                        segments=transcript_segments
                    )

                # Fallback to visual events or summary if no speech was detected
                if not srt_body.strip():
                    srt_body = generate_srt_from_events(
                        events=analysis.events,
                        total_duration=meta.get("duration"),
                        summary=analysis.summary or analysis.title
                    )

                if srt_body.strip():
                    srt_out = write_srt_sidecar(video_path, srt_body, conflict_mode=task.conflict_mode)
                    written_sidecars.append(str(srt_out))
                    self.log(f"Exported subtitle sidecar: {srt_out.name}", task_id=task.id)

            # 6. Optional In-file Tagging (Safe Mode)
            if cfg.enable_in_file_tagging:
                task.stage = "Applying in-file tags"
                self.log(f"Writing container tags to {video_path.name} with integrity check...", task_id=task.id)
                people_tags = [f"Person: {p}" for p in analysis.people_or_subjects]
                all_keywords = analysis.tags + people_tags
                tags = {
                    "title": analysis.title,
                    "description": analysis.summary,
                    "date": meta.get("creation_time", ""),
                    "keywords": ", ".join(all_keywords)
                }
                try:
                    apply_metadata_tags(
                        video_path,
                        tags=tags,
                        create_backup=cfg.backup_before_tagging,
                        flush_backup=getattr(cfg, "flush_backup_on_success", True),
                        verify_integrity=cfg.verify_integrity,
                        custom_ffmpeg=cfg.ffmpeg_path
                    )
                except Exception as tag_err:
                    self.log(
                        f"In-file container tagging skipped for {video_path.name}: {tag_err}. (Sidecars preserved)",
                        level="warning",
                        task_id=task.id
                    )

            # 7. Optional Suggested Rename
            suggested_name = generate_suggested_name(
                original_path=video_path,
                ai_title=analysis.suggested_filename or analysis.title,
                creation_date=meta.get("creation_time"),
                template=cfg.rename_template,
                suggested_slug=analysis.suggested_filename,
                collection_name=video_path.parent.name if video_path.parent else "",
                people_names=analysis.people_or_subjects,
                max_title_length=getattr(cfg, "max_title_length", 50),
                include_names_in_title=getattr(cfg, "include_names_in_title", False)
            )

            # Auto-rename if configured
            final_path = str(video_path)
            if cfg.auto_rename and suggested_name != video_path.name:
                task.stage = "Renaming file"
                ren_res = execute_rename(video_path, suggested_name)
                if ren_res.get("status") == "success":
                    final_path = ren_res.get("renamed_to", str(video_path))
                    old_name = video_path.name
                    task.file_path = final_path
                    task.filename = Path(final_path).name
                    video_path = Path(final_path)
                    self.log(f"Auto-renamed {old_name} -> {task.filename}", task_id=task.id)
                    # Update written_sidecars paths to match renamed sidecar locations
                    moved_map = {m["from"]: m["to"] for m in ren_res.get("sidecars_moved", [])}
                    written_sidecars = [moved_map.get(s, s) for s in written_sidecars]
                elif ren_res.get("status") == "skipped":
                    self.log(f"Auto-rename skipped for {video_path.name}: {ren_res.get('message', '')}", task_id=task.id)

            task.progress = 100
            task.stage = "Completed"
            task.status = "completed"
            task.completed_at = datetime.now().isoformat()
            task.result = {
                "title": analysis.title,
                "summary": analysis.summary,
                "events_count": len(analysis.events),
                "tags": analysis.tags,
                "people": analysis.people_or_subjects,
                "animals_or_pets": analysis.animals_or_pets,
                "objects": analysis.objects,
                "suggested_filename": suggested_name,
                "final_file_path": final_path,
                "audio_transcript": transcript or subtitle_dialogue,
                "sidecars": written_sidecars,
                "subtitles_used": bool(subtitles_found and cfg.use_subtitles),
                "subtitle_source": sub_source
            }
            self.log(f"Successfully processed {video_path.name}", task_id=task.id)

        except Exception as e:
            self.log(f"Error processing {video_path.name}: {e}", level="error", task_id=task.id)
            task.status = "failed"
            task.stage = "Failed"
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
        finally:
            # Enforce cache retention policy (default is 'immediate' removal of screenshots & audio)
            try:
                retention = cfg.temp_retention_policy
                if retention == "immediate":
                    freed = cleanup_video_cache(video_path)
                    self.log(f"Cleaned up temporary cache for {video_path.name} (policy: immediate)", task_id=task.id)
                elif retention in ("1_day", "7_days", "30_days"):
                    freed = purge_expired_cache(retention)
                    if freed > 0:
                        self.log(f"Purged expired cache items ({retention})", task_id=task.id)
            except Exception as clean_err:
                logger.warning(f"Error executing cache retention policy: {clean_err}")

manager = QueueManager()
