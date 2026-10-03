"""Thin loader for the TransNetV2 shot-boundary detector.

AIC-HCMC-2025 imported ``TransNetV2`` from a module that did not actually define
it; here we load the real TensorFlow inference class shipped in the repo at
``results/TransNetV2/inference/transnetv2.py`` (overridable via
TRANSNETV2_INFERENCE_DIR). That class exposes the API used by the pipeline:

    model = TransNetV2()
    _, single_frame_pred, _ = model.predict_video(video_path)
    scenes = model.predictions_to_scenes(single_frame_pred)   # [[start, end], ...]

See AIC-HCMC-2025/data_processing/transnetv2_setup.md for installing TensorFlow
and downloading the SavedModel weights.
"""
import importlib.util
import sys
from pathlib import Path

import config


def load_transnetv2():
    """Return an instantiated TransNetV2 model, ready for ``predict_video``."""
    # 1) Prefer a pip-installed `transnetv2` package if present.
    try:
        from transnetv2 import TransNetV2  # type: ignore
        return TransNetV2()
    except Exception:
        pass

    # 2) Fall back to the inference package vendored in the repo.
    inference_dir = Path(config.TRANSNETV2_INFERENCE_DIR)
    module_file = inference_dir / "transnetv2.py"
    if not module_file.exists():
        raise FileNotFoundError(
            f"Could not find TransNetV2 inference module at {module_file}. "
            "Set TRANSNETV2_INFERENCE_DIR or install the transnetv2 package "
            "(see transnetv2_setup.md)."
        )

    sys.path.insert(0, str(inference_dir))
    spec = importlib.util.spec_from_file_location("transnetv2_inference", module_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    weights_dir = inference_dir / "transnetv2-weights"
    if weights_dir.is_dir():
        return module.TransNetV2(model_dir=str(weights_dir))
    return module.TransNetV2()


def scenes_to_keyframe_indices(frame_ranges) -> list:
    """Pick representative frame indices from shot ranges.

    Mirrors AIC-HCMC-2025: take start+1 / middle / end-1 for shots longer than 4
    frames, otherwise just the two endpoints.
    """
    indices = []
    for start, end in frame_ranges:
        start, end = int(start), int(end)
        middle = (start + end) // 2
        if end - start > 4:
            indices.extend([start + 1, middle, end - 1])
        else:
            indices.extend([start + 1, end - 1])
    return indices
