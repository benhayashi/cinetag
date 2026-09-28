import json
import logging
import math
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None
from PIL import Image

try:
    import cv2
except ImportError:
    cv2 = None

from src.core.paths import get_faces_dir, get_base_data_dir
from src.core.config import AppConfig, load_config

logger = logging.getLogger(__name__)

YUNET_DOWNLOAD_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_FALLBACK_URL = "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

def get_face_model_path() -> Path:
    """Return path to YuNet face detection ONNX model, auto-downloading if missing."""
    repo_model = Path(__file__).resolve().parent.parent.parent / "models" / "face_detection_yunet.onnx"
    if repo_model.exists() and repo_model.stat().st_size > 50000:
        return repo_model

    data_model = get_base_data_dir() / "models" / "face_detection_yunet.onnx"
    if data_model.exists() and data_model.stat().st_size > 50000:
        return data_model

    target = repo_model if repo_model.parent.exists() else data_model
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        import urllib.request
        logger.info(f"Downloading YuNet face detection model (227KB) to {target}...")
        req = urllib.request.Request(YUNET_DOWNLOAD_URL, headers={"User-Agent": "CineTag/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            if len(data) > 50000:
                target.write_bytes(data)
                logger.info(f"Successfully downloaded face detection model ({len(data)} bytes).")
                return target
    except Exception as e:
        logger.warning(f"Primary YuNet model download failed: {e}. Trying fallback URL...")
        try:
            import urllib.request
            req = urllib.request.Request(YUNET_FALLBACK_URL, headers={"User-Agent": "CineTag/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 50000:
                    target.write_bytes(data)
                    logger.info(f"Successfully downloaded face detection model from fallback ({len(data)} bytes).")
                    return target
        except Exception as e2:
            logger.error(f"Fallback YuNet model download failed: {e2}")

    return repo_model

_MODEL_PATH = get_face_model_path()

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two feature vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    if np is not None:
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))

    # Pure Python fallback if NumPy is missing
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))

class FaceRegistry:
    """Persistent registry for recognized faces and auto-generated person clusters."""

    def __init__(self):
        self.faces_dir = get_faces_dir()
        self.registry_file = self.faces_dir / "registry.json"
        self.thumbs_dir = self.faces_dir / "thumbs"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading face registry: {e}")
        return {}

    def _save(self):
        try:
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving face registry: {e}")

    def get_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            faces = []
            for pid, info in self._data.items():
                shots = info.get("face_shots", [])
                faces.append({
                    "id": pid,
                    "name": info.get("name", pid),
                    "thumbnail": info.get("thumbnail"),
                    "thumbnail_url": f"/api/faces/thumbnail/{info.get('thumbnail')}" if info.get("thumbnail") else None,
                    "video_count": info.get("video_count", 0),
                    "video_paths": info.get("video_paths", []),
                    "created_at": info.get("created_at"),
                    "last_seen": info.get("last_seen"),
                    "is_named": not info.get("name", "").startswith("Person_"),
                    "user_named": info.get("user_named", False),
                    "ai_guessed": info.get("ai_guessed", False),
                    "shots_count": len(shots) if shots else (1 if info.get("thumbnail") else 0),
                    "face_shots": [
                        {
                            "filename": s.get("filename"),
                            "confidence": s.get("confidence", 0.8),
                            "url": f"/api/faces/thumbnail/{s.get('filename')}"
                        }
                        for s in shots
                    ]
                })
            faces.sort(key=lambda x: (x["video_count"], x["name"]), reverse=True)
            return faces

    def find_match(self, embedding: List[float], threshold: float = 0.55) -> Optional[Tuple[str, str, float]]:
        """Find best matching person in registry. Returns (person_id, name, score) or None."""
        with self._lock:
            best_match = None
            best_score = -1.0

            for pid, info in self._data.items():
                all_embs = [info.get("embedding")] + info.get("exemplars", [])
                candidate_scores = [cosine_similarity(embedding, e) for e in all_embs if e]
                score = max(candidate_scores) if candidate_scores else -1.0
                if score > best_score:
                    best_score = score
                    best_match = (pid, info.get("name", pid), score)

            if best_match and best_score >= threshold:
                return best_match
            return None

    def register_or_update(
        self,
        embedding: List[float],
        crop_image: Image.Image,
        video_path: str,
        assigned_name: Optional[str] = None,
        threshold: float = 0.55,
        confidence: float = 0.85
    ) -> Tuple[str, str]:
        """
        Match face to existing cluster or create a new auto-generated cluster.
        Maintains up to 10 top-quality face crops per identity.
        Returns (person_id, person_name).
        """
        with self._lock:
            match = None
            # If explicit name given from external system, check if subject name exists
            if assigned_name:
                for pid, info in self._data.items():
                    if info.get("name", "").strip().lower() == assigned_name.strip().lower():
                        match = (pid, info["name"], 1.0)
                        break

            # Otherwise match by vector across cluster centroid and exemplar poses/angles
            if not match:
                best_score = -1.0
                for pid, info in self._data.items():
                    all_embs = [info.get("embedding")] + info.get("exemplars", [])
                    candidate_scores = [cosine_similarity(embedding, e) for e in all_embs if e]
                    score = max(candidate_scores) if candidate_scores else -1.0
                    if score > best_score:
                        best_score = score
                        match = (pid, info.get("name", pid), score)

                if match and best_score < threshold:
                    match = None

            now_iso = datetime.now().isoformat()

            if match:
                pid, name, match_score = match
                entry = self._data[pid]
                entry["last_seen"] = now_iso
                vpaths = entry.setdefault("video_paths", [])
                if video_path not in vpaths:
                    vpaths.append(video_path)
                entry["video_count"] = len(vpaths)

                # Update running average embedding
                old_emb = np.array(entry["embedding"], dtype=np.float32)
                new_emb = np.array(embedding, dtype=np.float32)
                updated_emb = (old_emb * 0.75 + new_emb * 0.25)
                entry["embedding"] = (updated_emb / np.linalg.norm(updated_emb)).tolist()

                # Add diverse exemplars (angles, expressions) to improve multi-angle coherence
                exemplars = entry.setdefault("exemplars", [])
                if match_score < 0.90 and len(exemplars) < 6:
                    exemplars.append(embedding)
                elif len(exemplars) >= 6 and match_score < 0.85:
                    exemplars.pop(0)
                    exemplars.append(embedding)

                # Maintain up to 10 top-quality face shots
                shots = entry.setdefault("face_shots", [])
                if not shots and entry.get("thumbnail"):
                    shots.append({"filename": entry["thumbnail"], "confidence": 0.80, "timestamp": entry.get("created_at", now_iso)})

                crop_resized = crop_image.resize((150, 150), Image.Resampling.LANCZOS)
                if len(shots) < 10:
                    shot_filename = f"{pid}_shot_{len(shots) + 1:02d}.jpg"
                    crop_resized.save(self.thumbs_dir / shot_filename, "JPEG", quality=90)
                    shots.append({"filename": shot_filename, "confidence": float(confidence), "timestamp": now_iso})
                else:
                    # Keep only max quality: replace the lowest confidence shot if new one is better
                    min_idx, min_shot = min(enumerate(shots), key=lambda x: x[1].get("confidence", 0.0))
                    if confidence > min_shot.get("confidence", 0.0):
                        target_filename = min_shot.get("filename") or f"{pid}_shot_{min_idx + 1:02d}.jpg"
                        crop_resized.save(self.thumbs_dir / target_filename, "JPEG", quality=90)
                        shots[min_idx] = {"filename": target_filename, "confidence": float(confidence), "timestamp": now_iso}

                # Ensure primary thumbnail points to the highest quality shot
                if shots:
                    best_shot = max(shots, key=lambda s: s.get("confidence", 0.0))
                    entry["thumbnail"] = best_shot["filename"]
                    try:
                        shutil.copy2(self.thumbs_dir / best_shot["filename"], self.thumbs_dir / f"{pid}.jpg")
                    except Exception:
                        pass

                self._save()
                return pid, name
            else:
                # Create new cluster with auto-generated name
                existing_numbers = []
                for pid, info in self._data.items():
                    pname = info.get("name", "")
                    if pname.startswith("Person_"):
                        try:
                            num = int(pname.replace("Person_", ""))
                            existing_numbers.append(num)
                        except ValueError:
                            pass
                next_num = (max(existing_numbers) + 1) if existing_numbers else 1
                person_id = f"person_{next_num:03d}"
                person_name = assigned_name or f"Person_{next_num:02d}"

                shot_filename = f"{person_id}_shot_01.jpg"
                thumb_path = self.thumbs_dir / shot_filename
                crop_resized = crop_image.resize((150, 150), Image.Resampling.LANCZOS)
                crop_resized.save(thumb_path, "JPEG", quality=90)
                # Keep compatibility person_id.jpg
                try:
                    crop_resized.save(self.thumbs_dir / f"{person_id}.jpg", "JPEG", quality=90)
                except Exception:
                    pass

                norm = float(np.linalg.norm(embedding))
                emb_norm = (np.array(embedding, dtype=np.float32) / (norm if norm > 1e-6 else 1.0)).tolist()

                self._data[person_id] = {
                    "id": person_id,
                    "name": person_name,
                    "thumbnail": shot_filename,
                    "embedding": emb_norm,
                    "video_count": 1,
                    "video_paths": [video_path],
                    "created_at": now_iso,
                    "last_seen": now_iso,
                    "face_shots": [
                        {"filename": shot_filename, "confidence": float(confidence), "timestamp": now_iso}
                    ]
                }
                self._save()
                return person_id, person_name

    def rename_person(self, person_id: str, new_name: str, update_sidecars: bool = True, is_user: bool = True) -> Dict[str, Any]:
        """Rename a person identity and update associated video sidecars."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Name cannot be empty")

        with self._lock:
            if person_id not in self._data:
                raise KeyError(f"Person ID {person_id} not found")

            old_name = self._data[person_id].get("name", person_id)
            self._data[person_id]["name"] = new_name
            if is_user:
                self._data[person_id]["user_named"] = True
                self._data[person_id]["ai_guessed"] = False
            else:
                self._data[person_id]["ai_guessed"] = True
            video_paths = list(self._data[person_id].get("video_paths", []))
            self._save()

        updated_sidecars = []
        if update_sidecars and old_name != new_name:
            for vp_str in video_paths:
                vp = Path(vp_str)
                parent = vp.parent
                stem = vp.stem

                # 1. Update .info.json
                for json_cand in [parent / f"{stem}.info.json", parent / f"{vp.name}.info.json"]:
                    if json_cand.exists():
                        try:
                            with open(json_cand, "r", encoding="utf-8") as jf:
                                jdata = json.load(jf)
                            analysis = jdata.get("analysis", {})
                            people = analysis.get("people_or_subjects", [])
                            if old_name in people:
                                analysis["people_or_subjects"] = [new_name if p == old_name else p for p in people]
                                with open(json_cand, "w", encoding="utf-8") as jf:
                                    json.dump(jdata, jf, indent=2, ensure_ascii=False)
                                updated_sidecars.append(str(json_cand))
                        except Exception as e:
                            logger.warning(f"Error updating JSON sidecar {json_cand}: {e}")

                # 2. Update .xmp
                for xmp_cand in [parent / f"{stem}.xmp", parent / f"{vp.name}.xmp"]:
                    if xmp_cand.exists():
                        try:
                            content = xmp_cand.read_text(encoding="utf-8")
                            if old_name in content:
                                new_content = content.replace(f"<rdf:li>{old_name}</rdf:li>", f"<rdf:li>{new_name}</rdf:li>")
                                new_content = new_content.replace(f"Person:{old_name}", f"Person:{new_name}")
                                xmp_cand.write_text(new_content, encoding="utf-8")
                                updated_sidecars.append(str(xmp_cand))
                        except Exception as e:
                            logger.warning(f"Error updating XMP sidecar {xmp_cand}: {e}")

                # 3. Update .nfo
                for nfo_cand in [parent / f"{stem}.nfo", parent / f"{vp.name}.nfo"]:
                    if nfo_cand.exists():
                        try:
                            content = nfo_cand.read_text(encoding="utf-8")
                            if f"<name>{old_name}</name>" in content:
                                new_content = content.replace(f"<name>{old_name}</name>", f"<name>{new_name}</name>")
                                nfo_cand.write_text(new_content, encoding="utf-8")
                                updated_sidecars.append(str(nfo_cand))
                        except Exception as e:
                            logger.warning(f"Error updating NFO sidecar {nfo_cand}: {e}")

                # 4. Update .txt
                for txt_cand in [parent / f"{vp.name}.txt", parent / f"{stem}.txt"]:
                    if txt_cand.exists():
                        try:
                            content = txt_cand.read_text(encoding="utf-8")
                            if old_name in content:
                                new_content = content.replace(old_name, new_name)
                                txt_cand.write_text(new_content, encoding="utf-8")
                                updated_sidecars.append(str(txt_cand))
                        except Exception as e:
                            logger.warning(f"Error updating TXT sidecar {txt_cand}: {e}")

        return {
            "status": "renamed",
            "person_id": person_id,
            "old_name": old_name,
            "new_name": new_name,
            "updated_sidecars_count": len(updated_sidecars)
        }

    def correlate_and_guess_names(
        self,
        detected_face_ids: List[str],
        ai_people_names: List[str],
        video_path: str,
        summary: str = ""
    ) -> List[Dict[str, str]]:
        """
        Use AI vision descriptions/subjects to guess names for unnamed face clusters in this video.
        STRICT RULE: Never overwrites faces that were previously customized or named by user (user_named == True).
        """
        matches = []
        with self._lock:
            unnamed_pids = []
            for pid in detected_face_ids:
                if pid in self._data:
                    info = self._data[pid]
                    if info.get("user_named"):
                        continue
                    current_name = info.get("name", "")
                    if current_name.startswith("Person_") or not info.get("user_named"):
                        if pid not in unnamed_pids:
                            unnamed_pids.append(pid)

            if not unnamed_pids or not ai_people_names:
                return []

            valid_names = []
            for n in ai_people_names:
                clean = n.strip()
                if not clean:
                    continue
                lower = clean.lower()
                if lower in ("person", "people", "man", "woman", "child", "boy", "girl", "someone", "unknown", "crowd", "audience"):
                    continue
                if clean not in valid_names:
                    valid_names.append(clean)

            if not valid_names:
                return []

            if len(unnamed_pids) == 1 and len(valid_names) == 1:
                pid = unnamed_pids[0]
                target_name = valid_names[0]
                if self._data[pid].get("name") != target_name:
                    old = self._data[pid].get("name", pid)
                    self.rename_person(pid, target_name, update_sidecars=True, is_user=False)
                    matches.append({"person_id": pid, "old_name": old, "new_name": target_name})
            else:
                for i, pid in enumerate(unnamed_pids):
                    if i < len(valid_names):
                        target_name = valid_names[i]
                        if self._data[pid].get("name") != target_name:
                            old = self._data[pid].get("name", pid)
                            self.rename_person(pid, target_name, update_sidecars=True, is_user=False)
                            matches.append({"person_id": pid, "old_name": old, "new_name": target_name})

        return matches

    def auto_guess_all_unnamed_faces(self) -> List[Dict[str, str]]:
        """
        Scan all registered persons in database; if a person has video_paths,
        inspect the sidecar .info.json files of those videos to find AI people_or_subjects
        and attempt auto-naming.
        """
        all_matches = []
        with self._lock:
            for pid, info in list(self._data.items()):
                if info.get("user_named"):
                    continue
                if not info.get("name", "").startswith("Person_"):
                    continue
                vpaths = info.get("video_paths", [])
                for vp_str in vpaths:
                    vp = Path(vp_str)
                    parent = vp.parent
                    stem = vp.stem
                    for jcand in [parent / f"{stem}.info.json", parent / f"{vp.name}.info.json"]:
                        if jcand.exists():
                            try:
                                with open(jcand, "r", encoding="utf-8") as jf:
                                    jdata = json.load(jf)
                                analysis = jdata.get("analysis", {})
                                people = analysis.get("people_or_subjects", [])
                                valid = [
                                    p.strip() for p in people
                                    if p.strip() and not p.strip().startswith("Person_")
                                    and p.strip().lower() not in ("person", "people", "man", "woman", "child", "boy", "girl")
                                ]
                                if valid:
                                    for cand_name in valid:
                                        if not any(other.get("name") == cand_name and other.get("user_named") for other in self._data.values()):
                                            old = info.get("name", pid)
                                            self.rename_person(pid, cand_name, update_sidecars=True, is_user=False)
                                            all_matches.append({"person_id": pid, "old_name": old, "new_name": cand_name})
                                            break
                            except Exception:
                                pass
                        if info.get("name", "") != pid and not info.get("name", "").startswith("Person_"):
                            break
        return all_matches

    def merge_persons(self, source_id: str, target_id: str) -> Dict[str, Any]:
        """Merge source person cluster into target person cluster."""
        with self._lock:
            if source_id not in self._data or target_id not in self._data:
                raise KeyError("Invalid person ID for merge")

            src = self._data[source_id]
            tgt = self._data[target_id]

            # Merge video paths
            combined_videos = list(set(tgt.get("video_paths", []) + src.get("video_paths", [])))
            tgt["video_paths"] = combined_videos
            tgt["video_count"] = len(combined_videos)

            # Update embedding
            v_src = np.array(src["embedding"], dtype=np.float32)
            v_tgt = np.array(tgt["embedding"], dtype=np.float32)
            v_merged = (v_tgt * 0.7 + v_src * 0.3)
            tgt["embedding"] = (v_merged / np.linalg.norm(v_merged)).tolist()

            # Merge exemplars (up to 6)
            combined_ex = tgt.get("exemplars", []) + src.get("exemplars", []) + [src["embedding"]]
            tgt["exemplars"] = combined_ex[:6]

            # Merge face_shots (up to 10 top quality)
            combined_shots = tgt.get("face_shots", []) + src.get("face_shots", [])
            seen_files = set()
            unique_shots = []
            for s in combined_shots:
                if s.get("filename") and s.get("filename") not in seen_files:
                    seen_files.add(s.get("filename"))
                    unique_shots.append(s)
            unique_shots.sort(key=lambda s: s.get("confidence", 0.0), reverse=True)
            tgt["face_shots"] = unique_shots[:10]
            if tgt["face_shots"]:
                tgt["thumbnail"] = tgt["face_shots"][0]["filename"]

            del self._data[source_id]
            self._save()

        # Update sidecars to use target's name
        self.rename_person(target_id, tgt["name"], update_sidecars=True)
        return {"status": "merged", "kept_id": target_id, "deleted_id": source_id, "name": tgt["name"]}

    def recluster_and_reindex(self, threshold: float = 0.55) -> Dict[str, Any]:
        """
        Re-evaluates and merges existing person clusters using the given similarity threshold.
        If two identities exceed the similarity threshold (or are within distance tolerance),
        they are merged together into a unified identity.
        """
        with self._lock:
            merged_count = 0
            pids = list(self._data.keys())
            i = 0
            while i < len(pids):
                pid_a = pids[i]
                if pid_a not in self._data:
                    i += 1
                    continue
                info_a = self._data[pid_a]
                embs_a = [info_a.get("embedding")] + info_a.get("exemplars", [])

                j = i + 1
                while j < len(pids):
                    pid_b = pids[j]
                    if pid_b not in self._data:
                        j += 1
                        continue
                    info_b = self._data[pid_b]
                    embs_b = [info_b.get("embedding")] + info_b.get("exemplars", [])

                    max_sim = max((cosine_similarity(ea, eb) for ea in embs_a if ea for eb in embs_b if eb), default=0.0)
                    if max_sim >= threshold:
                        # Keep custom name if one exists
                        is_named_a = not info_a.get("name", "").startswith("Person_")
                        is_named_b = not info_b.get("name", "").startswith("Person_")
                        if not is_named_a and is_named_b:
                            target_id, source_id = pid_b, pid_a
                        else:
                            target_id, source_id = pid_a, pid_b

                        self.merge_persons(source_id, target_id)
                        merged_count += 1
                        pids = list(self._data.keys())
                        i = -1
                        break
                    j += 1
                i += 1

            return {
                "status": "ok",
                "merged_count": merged_count,
                "total_identities": len(self._data)
            }

    def delete_person(self, person_id: str) -> bool:
        with self._lock:
            if person_id in self._data:
                for shot in self._data[person_id].get("face_shots", []):
                    s_file = self.thumbs_dir / shot.get("filename", "")
                    if s_file.exists():
                        try:
                            s_file.unlink()
                        except Exception:
                            pass
                thumb = self._data[person_id].get("thumbnail")
                if thumb:
                    thumb_path = self.thumbs_dir / thumb
                    if thumb_path.exists():
                        try:
                            thumb_path.unlink()
                        except Exception:
                            pass
                pid_thumb = self.thumbs_dir / f"{person_id}.jpg"
                if pid_thumb.exists():
                    try:
                        pid_thumb.unlink()
                    except Exception:
                        pass
                del self._data[person_id]
                self._save()
                return True
            return False

    def clear_all(self) -> int:
        """Clear all registered face identities and delete saved face thumbnails."""
        with self._lock:
            count = len(self._data)
            self._data.clear()
            self._save()
            if self.thumbs_dir.exists():
                for thumb_file in self.thumbs_dir.glob("*.jpg"):
                    try:
                        thumb_file.unlink()
                    except Exception:
                        pass
            return count

    def register_named_subject(
        self,
        name: str,
        video_path: str,
        frame_path: Optional[Path] = None,
        candidate_frames: Optional[List[Path]] = None
    ) -> Tuple[str, str]:
        """Register or associate a named subject identified from video analysis."""
        with self._lock:
            clean_name = name.strip()
            if not clean_name:
                return "", ""

            match_id = None
            for pid, info in self._data.items():
                if info.get("name", "").strip().lower() == clean_name.lower():
                    match_id = pid
                    break

            now_iso = datetime.now().isoformat()

            def _extract_subject_thumb(target_thumb_path: Path) -> Tuple[bool, Optional[List[float]]]:
                all_cands: List[Path] = []
                if frame_path and frame_path.exists():
                    all_cands.append(frame_path)
                if candidate_frames:
                    for cf in candidate_frames:
                        if cf and cf.exists() and cf not in all_cands:
                            all_cands.append(cf)

                face_crop = None
                face_emb = None
                for cf in all_cands:
                    try:
                        for conf in (0.60, 0.45):
                            faces = LocalFaceEngine.detect_and_embed(cf, confidence=conf)
                            if faces:
                                face_crop = faces[0]["crop"]
                                face_emb = faces[0].get("embedding")
                                break
                        if face_crop:
                            break
                    except Exception as e:
                        logger.warning(f"Could not extract face from candidate frame {cf}: {e}")

                if face_crop:
                    crop_resized = face_crop.resize((150, 150), Image.Resampling.LANCZOS)
                    crop_resized.save(target_thumb_path, "JPEG", quality=90)
                    return True, face_emb
                return False, None

            if match_id:
                entry = self._data[match_id]
                entry["last_seen"] = now_iso
                vpaths = entry.setdefault("video_paths", [])
                if video_path not in vpaths:
                    vpaths.append(video_path)
                entry["video_count"] = len(vpaths)

                thumb_filename = entry.get("thumbnail") or f"{match_id}.jpg"
                thumb_path = self.thumbs_dir / thumb_filename
                if not thumb_path.exists():
                    created, new_emb = _extract_subject_thumb(thumb_path)
                    if created:
                        entry["thumbnail"] = thumb_filename
                        shots = entry.setdefault("face_shots", [])
                        if not shots:
                            shots.append({"filename": thumb_filename, "confidence": 0.85, "timestamp": now_iso})
                        if new_emb and all(x == 0.0 for x in entry.get("embedding", [])):
                            entry["embedding"] = new_emb

                self._save()
                return match_id, entry["name"]
            else:
                existing_numbers = []
                for pid in self._data.keys():
                    if pid.startswith("person_"):
                        try:
                            num = int(pid.replace("person_", ""))
                            existing_numbers.append(num)
                        except ValueError:
                            pass
                next_num = (max(existing_numbers) + 1) if existing_numbers else 1
                person_id = f"person_{next_num:03d}"
                thumb_filename = f"{person_id}.jpg"
                thumb_path = self.thumbs_dir / thumb_filename

                created, face_emb = _extract_subject_thumb(thumb_path)

                dummy_emb = face_emb or ([0.0] * 128)
                self._data[person_id] = {
                    "id": person_id,
                    "name": clean_name,
                    "thumbnail": thumb_filename if thumb_path.exists() else None,
                    "embedding": dummy_emb,
                    "video_count": 1,
                    "video_paths": [video_path],
                    "created_at": now_iso,
                    "last_seen": now_iso,
                    "face_shots": [
                        {"filename": thumb_filename, "confidence": 0.85, "timestamp": now_iso}
                    ] if thumb_path.exists() else []
                }
                self._save()
                return person_id, clean_name

    def export_database_zip(self, output_path: Path) -> Path:
        """Package registry.json and face thumbnails into a portable .zip file."""
        import zipfile
        with self._lock:
            self._save()
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if self.registry_file.exists():
                    zf.write(self.registry_file, arcname="registry.json")
                if self.thumbs_dir.exists():
                    for thumb in self.thumbs_dir.glob("*.jpg"):
                        zf.write(thumb, arcname=f"thumbs/{thumb.name}")
        return output_path

    def import_database_zip(self, zip_path: Path, merge: bool = True) -> int:
        """Restore face registry and thumbnails from a .zip archive."""
        import zipfile
        imported_count = 0
        with self._lock:
            with zipfile.ZipFile(zip_path, "r") as zf:
                namelist = zf.namelist()
                if "registry.json" not in namelist:
                    raise ValueError("Invalid archive: missing registry.json")

                with zf.open("registry.json") as f:
                    incoming_data = json.load(f)

                # Extract thumbs safely
                for member in namelist:
                    if member.startswith("thumbs/") and (member.endswith(".jpg") or member.endswith(".png")):
                        filename = Path(member).name
                        dest = self.thumbs_dir / filename
                        with zf.open(member) as src_f, open(dest, "wb") as dst_f:
                            dst_f.write(src_f.read())

                if not merge:
                    self._data = incoming_data
                    imported_count = len(incoming_data)
                else:
                    for pid, info in incoming_data.items():
                        if pid in self._data:
                            cur_vpaths = self._data[pid].setdefault("video_paths", [])
                            for vp in info.get("video_paths", []):
                                if vp not in cur_vpaths:
                                    cur_vpaths.append(vp)
                            self._data[pid]["video_count"] = len(cur_vpaths)
                            if self._data[pid].get("name", "").startswith("Person_") and not info.get("name", "").startswith("Person_"):
                                self._data[pid]["name"] = info.get("name")
                        else:
                            self._data[pid] = info
                            imported_count += 1

                self._save()
        return imported_count

    def backfill_missing_thumbnails(self) -> int:
        """
        Scan all registered persons; for any person without a valid thumbnail,
        inspect their associated video_paths, extract frames/faces,
        and generate a thumbnail image.
        Returns count of thumbnails successfully backfilled.
        """
        from src.media.sampler import extract_frames
        count = 0
        with self._lock:
            for pid, info in list(self._data.items()):
                thumb = info.get("thumbnail")
                if thumb and (self.thumbs_dir / thumb).exists():
                    continue

                vpaths = info.get("video_paths", [])
                for vp_str in vpaths:
                    vp = Path(vp_str)
                    if not vp.exists():
                        continue

                    try:
                        frames = extract_frames(vp, interval_seconds=10, max_frames=5, max_dimension=512)
                        fpaths = [Path(f["path"]) for f in frames if "path" in f]

                        thumb_filename = f"{pid}.jpg"
                        thumb_path = self.thumbs_dir / thumb_filename
                        face_crop = None
                        face_emb = None

                        for fp in fpaths:
                            for conf in (0.60, 0.45):
                                faces = LocalFaceEngine.detect_and_embed(fp, confidence=conf)
                                if faces:
                                    face_crop = faces[0]["crop"]
                                    face_emb = faces[0].get("embedding")
                                    break
                            if face_crop:
                                break

                        if face_crop:
                            crop_resized = face_crop.resize((150, 150), Image.Resampling.LANCZOS)
                            crop_resized.save(thumb_path, "JPEG", quality=90)
                            info["thumbnail"] = thumb_filename
                            shots = info.setdefault("face_shots", [])
                            if not shots:
                                shots.append({"filename": thumb_filename, "confidence": 0.85, "timestamp": datetime.now().isoformat()})
                            if face_emb and all(x == 0.0 for x in info.get("embedding", [])):
                                info["embedding"] = face_emb
                            count += 1
                            break
                    except Exception as e:
                        logger.warning(f"Could not backfill thumbnail for {pid} from {vp}: {e}")

            if count > 0:
                self._save()
        return count

# Global registry instance
face_registry = FaceRegistry()


# --- Local Feature & Face Detector Engine ---

class LocalFaceEngine:
    """
    Lightweight, high-accuracy face detector and embedding generator.
    Uses OpenCV's YuNet neural face detector on CPU (models/face_detection_yunet.onnx).
    Accurately detects real human faces with eye, nose, mouth landmarks and strictly
    filters out non-face body parts like hands, elbows, arms, knees, and background patterns.
    """

    @classmethod
    def _get_detector(cls, w: int, h: int, confidence: float = 0.70):
        """Create or configure a FaceDetectorYN instance for given image dimensions."""
        model_path = get_face_model_path()
        if cv2 is None or not model_path.exists():
            logger.warning(f"YuNet model or cv2 unavailable (model={model_path.exists()})")
            return None
        try:
            detector = cv2.FaceDetectorYN_create(
                str(model_path),
                "",
                (w, h),
                score_threshold=float(confidence),
                nms_threshold=0.3,
                top_k=5000
            )
            return detector
        except Exception as e:
            logger.error(f"Failed to initialize FaceDetectorYN: {e}")
            return None

    @classmethod
    def detect_and_embed(cls, image_path: Path, confidence: float = 0.60) -> List[Dict[str, Any]]:
        """
        Analyze frame with YuNet face detector, crop face bounding box,
        and generate 128-dimensional normalized facial embedding.
        Returns list of dicts: {'box': (ymin, xmin, ymax, xmax), 'crop': PIL.Image, 'embedding': List[float], 'confidence': float}
        """
        try:
            with Image.open(image_path) as img:
                img_rgb = img.convert("RGB")
                img_w, img_h = img_rgb.size
                model_path = get_face_model_path()

                if cv2 is not None and model_path.exists():
                    arr_rgb = np.array(img_rgb, dtype=np.uint8)
                    img_bgr = cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)

                    detector = cls._get_detector(img_w, img_h, confidence=confidence)
                    if detector is not None:
                        ret, faces = detector.detect(img_bgr)
                        if faces is None or len(faces) == 0:
                            return []

                        detected_faces = []
                        for face in faces:
                            x = int(face[0])
                            y = int(face[1])
                            w = int(face[2])
                            h = int(face[3])
                            score = float(face[14])

                            if score < confidence:
                                continue
                            if w < 20 or h < 20:
                                continue

                            # Gentle margin (12% width, 18% height) to frame face naturally
                            pad_x = int(w * 0.12)
                            pad_y = int(h * 0.18)

                            xmin = max(0, x - pad_x)
                            ymin = max(0, y - pad_y)
                            xmax = min(img_w, x + w + pad_x)
                            ymax = min(img_h, y + h + pad_y)

                            if xmax <= xmin or ymax <= ymin:
                                continue

                            face_crop = img_rgb.crop((xmin, ymin, xmax, ymax))
                            emb = cls._compute_embedding(face_crop)
                            detected_faces.append({
                                "box": (ymin, xmin, ymax, xmax),
                                "crop": face_crop,
                                "embedding": emb,
                                "confidence": score
                            })
                        return detected_faces

                # If model or cv2 is not present (mock fallback), return empty list
                return []
        except Exception as e:
            logger.warning(f"Face detection failed for {image_path}: {e}")
            return []

    @staticmethod
    def _compute_embedding(crop: Image.Image) -> List[float]:
        """Generate a 128-dimensional normalized feature vector from a face crop with illumination invariance."""
        resized = crop.resize((32, 32), Image.Resampling.BILINEAR).convert("L")
        data = np.array(resized, dtype=np.float32)

        # Local contrast normalization (zero-mean, unit-variance) for illumination invariance
        d_mean = float(np.mean(data))
        d_std = float(np.std(data))
        if d_std > 1e-4:
            data = (data - d_mean) / d_std
        else:
            data = data - d_mean

        # 1. 8x8 block average intensities (64 dimensions)
        blocks_8x8 = data.reshape(8, 4, 8, 4).mean(axis=(1, 3)).flatten()
        blocks_norm = blocks_8x8 / (np.linalg.norm(blocks_8x8) + 1e-6)

        # 2. Horizontal & vertical directional gradients (64 dimensions)
        grad_x = np.diff(data, axis=1)  # 32x31
        grad_y = np.diff(data, axis=0)  # 31x32

        # Pool gradients into 8x4 blocks
        gx_pool = grad_x[:, :28].reshape(8, 4, 7, 4).mean(axis=(1, 3)).flatten()[:32]
        gy_pool = grad_y[:28, :].reshape(7, 4, 8, 4).mean(axis=(1, 3)).flatten()[:32]

        grad_vec = np.concatenate([gx_pool, gy_pool])
        grad_norm = grad_vec / (np.linalg.norm(grad_vec) + 1e-6)

        # Combined 128-dimensional vector
        vec = np.concatenate([blocks_norm, grad_norm])
        final_norm = vec / (np.linalg.norm(vec) + 1e-6)
        return final_norm.tolist()


# --- CompreFace External Connector ---

class CompreFaceConnector:
    """Client for external self-hosted CompreFace recognition service."""

    @staticmethod
    def recognize_frame(
        image_path: Path,
        compreface_url: str,
        api_key: str,
        threshold: float = 0.62
    ) -> List[Dict[str, Any]]:
        """
        Query CompreFace REST API: POST /api/v1/recognition/recognize
        Returns list of dicts: {'name': str, 'similarity': float, 'box': tuple}
        """
        import httpx

        url = compreface_url.rstrip("/") + "/api/v1/recognition/recognize"
        headers = {"x-api-key": api_key}
        params = {"limit": 0, "det_prob_threshold": 0.8}

        results = []
        try:
            with open(image_path, "rb") as f:
                files = {"file": (image_path.name, f, "image/jpeg")}
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, headers=headers, params=params, files=files)
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_results = data.get("result", [])
                        for item in raw_results:
                            box = item.get("box", {})
                            subjects = item.get("subjects", [])
                            if subjects:
                                best_subj = subjects[0]
                                sim = best_subj.get("similarity", 0.0)
                                if sim >= threshold:
                                    results.append({
                                        "name": best_subj.get("subject"),
                                        "similarity": sim,
                                        "box": (box.get("y_min", 0), box.get("x_min", 0), box.get("y_max", 0), box.get("x_max", 0))
                                    })
                            else:
                                # Detected face but unknown subject
                                results.append({
                                    "name": None,
                                    "similarity": 0.0,
                                    "box": (box.get("y_min", 0), box.get("x_min", 0), box.get("y_max", 0), box.get("x_max", 0))
                                })
                    else:
                        logger.warning(f"CompreFace returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"CompreFace connection error: {e}")

        return results


# --- Pipeline Orchestrator ---

def process_video_faces(
    frames: List[Any],  # List of FrameItem or dicts with 'path' and 'timecode'
    cfg: AppConfig,
    video_path: Path
) -> List[Dict[str, Any]]:
    """
    Main face analysis routine executed during video processing queue.
    Detects faces, clusters/recognizes them, and returns recognized subjects.
    """
    if not cfg.face_recognition_enabled:
        return []

    recognized_people: Dict[str, Dict[str, Any]] = {}

    for frame in frames:
        fpath = Path(frame.path if hasattr(frame, "path") else frame["path"])
        timecode = frame.timecode if hasattr(frame, "timecode") else frame.get("timecode", "00:00")
        if not fpath.exists():
            continue

        # Strategy 1: External CompreFace if configured
        if cfg.face_provider == "compreface" and cfg.compreface_url and cfg.compreface_api_key:
            ext_results = CompreFaceConnector.recognize_frame(
                fpath,
                cfg.compreface_url,
                cfg.compreface_api_key,
                cfg.face_match_threshold
            )
            for res in ext_results:
                name = res.get("name")
                if name:
                    # Register into local registry to track videos
                    dummy_emb = [0.0] * 128
                    try:
                        with Image.open(fpath) as img:
                            ymin, xmin, ymax, xmax = res["box"]
                            crop = img.crop((xmin, ymin, xmax, ymax)) if xmax > xmin and ymax > ymin else img
                            pid, assigned_name = face_registry.register_or_update(
                                embedding=LocalFaceEngine._compute_embedding(crop),
                                crop_image=crop,
                                video_path=str(video_path.resolve()),
                                assigned_name=name,
                                threshold=cfg.face_match_threshold
                            )
                            if name not in recognized_people:
                                recognized_people[name] = {
                                    "name": name,
                                    "person_id": pid,
                                    "id": pid,
                                    "timecode": timecode,
                                    "confidence": res.get("similarity", 1.0)
                                }
                    except Exception:
                        pass

        # Strategy 2: Local Built-in Face Engine (Default or Fallback)
        else:
            detections = LocalFaceEngine.detect_and_embed(fpath, confidence=cfg.face_detection_confidence)
            match_thresh = cfg.face_match_threshold
            if hasattr(cfg, "face_max_distance") and cfg.face_max_distance is not None:
                match_thresh = 1.0 - cfg.face_max_distance

            for det in detections:
                pid, name = face_registry.register_or_update(
                    embedding=det["embedding"],
                    crop_image=det["crop"],
                    video_path=str(video_path.resolve()),
                    threshold=match_thresh,
                    confidence=det.get("confidence", 0.85)
                )
                if name not in recognized_people:
                    recognized_people[name] = {
                        "name": name,
                        "person_id": pid,
                        "id": pid,
                        "timecode": timecode,
                        "confidence": det.get("confidence", 0.85)
                    }

    return list(recognized_people.values())
