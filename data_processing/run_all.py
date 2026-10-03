"""Run the full HCM-AIC-2026 data-processing pipeline end to end.

The embedding backbone for the features/faiss stages is config.MODEL_KEY
(clip | siglip | jina | beit3), overridable via the MODEL_KEY env var.

Usage:
    python run_all.py                 # keyframes(TransNetV2) -> features -> faiss -> ocr -> asr
    MODEL_KEY=siglip python run_all.py
    python run_all.py --from-map      # use official map-keyframes CSVs (step 01b)
    python run_all.py --skip ocr asr  # skip specific stages

Each stage is an independent, resumable script and can also be run on its own
(see the numbered files). They are imported and called here for convenience.
"""
import argparse
import importlib


STAGES = [
    ("keyframes", "01_extract_keyframes"),
    ("features", "02_extract_features"),
    ("faiss", "03_build_faiss_index"),
    ("keyframe_index", "03b_build_keyframe_index"),
    ("ocr", "04_extract_ocr"),
    ("asr", "05_extract_asr"),
    ("graph", "08_build_graph"),
]


def run(module_name: str) -> None:
    print(f"\n{'=' * 70}\n[RUN] {module_name}\n{'=' * 70}")
    importlib.import_module(module_name).main()


def main() -> None:
    parser = argparse.ArgumentParser(description="HCM-AIC-2026 data pipeline")
    parser.add_argument("--from-map", action="store_true",
                        help="extract keyframes from official map CSVs (01b) instead of TransNetV2")
    parser.add_argument("--skip", nargs="*", default=[],
                        help="stage names to skip: keyframes features faiss keyframe_index ocr asr graph")
    args = parser.parse_args()

    for name, module_name in STAGES:
        if name in args.skip:
            print(f"[SKIP] {name}")
            continue
        if name == "keyframes" and args.from_map:
            module_name = "01b_keyframes_from_map"
        run(module_name)

    print("\n[DONE] Pipeline complete.")


if __name__ == "__main__":
    main()
