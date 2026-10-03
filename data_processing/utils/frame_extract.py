"""Frame extraction + naming helpers.

Ported from AIC-HCMC-2025/data_processing/frame_extract.py and extended with the
naming conventions the HCM-AIC-2026 backend expects:

    video_name   "L21_V001"                      (basename of the .mp4, no ext)
    frame_name   "000080.jpg"                     (zero-padded frame index)
    frame_id     "L21_V001_000080"                (video_name + "_" + frame index)

The backend's metadata_service infers meta from frame_id via
``frame_id.rsplit("_", 1)`` so the frame index MUST be the final "_"-segment and
be purely numeric.
"""
import os

import cv2

FRAME_INDEX_PAD = 6  # zero-pad frame indices -> "000080"


def video_name_of(video_path: str) -> str:
    return os.path.splitext(os.path.basename(video_path))[0]


def frame_name_of(frame_index: int, ext: str = "jpg") -> str:
    return f"{int(frame_index):0{FRAME_INDEX_PAD}d}.{ext}"


def frame_id_of(video_name: str, frame_index: int) -> str:
    return f"{video_name}_{int(frame_index):0{FRAME_INDEX_PAD}d}"


def get_video_fps(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return float(fps) if fps and fps > 0 else 25.0


def extract_and_save_frame(video_path, frame_id, save_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_id < 0 or frame_id >= total_frames:
        cap.release()
        raise IndexError(f"frame_id {frame_id} is out of range (0 to {total_frames - 1})")

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    success, frame = cap.read()
    cap.release()
    if not success:
        raise RuntimeError(f"Failed to read frame at position {frame_id}")

    if not cv2.imwrite(save_path, frame):
        raise RuntimeError(f"Failed to write frame to {save_path}")


def extract_resize_and_save_frame(video_path, frame_id, save_path, scale=0.5):
    if scale <= 0 or scale > 1:
        raise ValueError("Scale must be between 0 and 1 (exclusive of 0)")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_id < 0 or frame_id >= total_frames:
        cap.release()
        raise IndexError(f"frame_id {frame_id} is out of range (0 to {total_frames - 1})")

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
    success, frame = cap.read()
    cap.release()
    if not success:
        raise RuntimeError(f"Failed to read frame at position {frame_id}")

    height, width = frame.shape[:2]
    new_size = (int(width * scale), int(height * scale))
    resized_frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

    if not cv2.imwrite(save_path, resized_frame):
        raise RuntimeError(f"Failed to write resized frame to {save_path}")
