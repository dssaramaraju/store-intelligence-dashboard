from pathlib import Path
import sys
from typing import Any

import cv2


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


def discover_videos(input_dir: Path) -> list[Path]:
    cctv_dir = input_dir / "cctv"
    if not cctv_dir.exists():
        return sorted(path for path in input_dir.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS)
    return sorted(path for path in cctv_dir.iterdir() if path.suffix.lower() in VIDEO_EXTENSIONS)


def camera_id_for_video(path: Path) -> str:
    stem = path.stem.upper().replace(" ", "_").replace("-", "_")
    if stem.startswith("CAM_"):
        return stem
    return f"CAM_{stem}"


def camera_role(camera_id: str) -> str:
    normalized = camera_id.upper()
    if "ENTRY" in normalized:
        return "entry"
    if "BILL" in normalized:
        return "billing"
    if normalized in {"CAM_1", "CAM_5"}:
        return "entry"
    if normalized == "CAM_3":
        return "billing"
    return "floor"


def zone_for_camera(camera_id: str, index: int = 0) -> str:
    role = camera_role(camera_id)
    if role == "entry":
        return "ENTRY_THRESHOLD"
    if role == "billing":
        return "BILLING"
    zones = ["SKINCARE", "MAKEUP", "BATH_AND_BODY", "HAIRCARE", "FRAGRANCE"]
    return zones[index % len(zones)]


def analyze_video(path: Path, sample_seconds: float = 2.0, max_samples: int = 180, verbose: bool = False) -> dict[str, Any]:
    if verbose:
        print(f"[cctv] opening {path.name}", file=sys.stderr, flush=True)
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {
            "path": str(path),
            "camera_id": camera_id_for_video(path),
            "opened": False,
            "fps": 0.0,
            "duration_seconds": 0.0,
            "activity": [],
        }

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration_seconds = frame_count / fps if fps else 0.0
    step_frames = max(int(fps * sample_seconds), 1)
    subtractor = cv2.createBackgroundSubtractorMOG2(history=80, varThreshold=36, detectShadows=True)
    camera_id = camera_id_for_video(path)
    activity: list[dict[str, Any]] = []

    frame_index = 0
    samples = 0
    while samples < max_samples:
        if verbose and samples and samples % 30 == 0:
            print(f"[cctv] {path.name}: sampled {samples}/{max_samples} frames", file=sys.stderr, flush=True)
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            break

        resized = cv2.resize(frame, (480, 270))
        mask = subtractor.apply(resized)
        _, threshold = cv2.threshold(mask, 244, 255, cv2.THRESH_BINARY)
        threshold = cv2.medianBlur(threshold, 5)
        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 450:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if h < 24 or w < 10:
                continue
            boxes.append((x, y, w, h, area))

        person_estimate = min(len(boxes), 6)
        motion_area = int(sum(box[-1] for box in boxes))
        if person_estimate > 0:
            activity.append(
                {
                    "time_seconds": round(frame_index / fps, 2),
                    "person_estimate": person_estimate,
                    "motion_area": motion_area,
                    "confidence": min(0.95, 0.45 + person_estimate * 0.12 + min(motion_area / 40000, 0.2)),
                    "zone_id": zone_for_camera(camera_id, samples),
                }
            )

        samples += 1
        frame_index += step_frames

    capture.release()
    if verbose:
        print(f"[cctv] {path.name}: activity_samples={len(activity)} duration_seconds={round(float(duration_seconds), 2)}", file=sys.stderr, flush=True)
    return {
        "path": str(path),
        "camera_id": camera_id,
        "opened": True,
        "fps": round(float(fps), 2),
        "duration_seconds": round(float(duration_seconds), 2),
        "activity": activity,
    }


def analyze_videos(input_dir: Path, verbose: bool = False) -> list[dict[str, Any]]:
    return [analyze_video(path, verbose=verbose) for path in discover_videos(input_dir)]
