#!/usr/bin/env python3
"""Perform a structural check of a converted LeRobot dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq


def fail(message: str) -> int:
    print(f"LeRobot output verification failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--format", choices=("lerobot_v2.1", "lerobot_v3.0"), required=True
    )
    args = parser.parse_args()

    info_path = args.dataset / "meta" / "info.json"
    if not info_path.is_file():
        return fail(f"missing {info_path}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    expected_version = args.format.removeprefix("lerobot_")
    if info.get("codebase_version") != expected_version:
        return fail(
            f"codebase_version={info.get('codebase_version')!r}, expected {expected_version!r}"
        )
    if int(info.get("total_episodes", 0)) <= 0 or int(
        info.get("total_frames", 0)
    ) <= 0:
        return fail("metadata reports no episodes or frames")

    parquet_files = sorted((args.dataset / "data").rglob("*.parquet"))
    if not parquet_files:
        return fail("no data parquet files were written")
    required = {"action", "observation.state", "timestamp", "episode_index"}
    schema_names = set(pq.read_schema(parquet_files[0]).names)
    missing = required - schema_names
    if missing:
        return fail(f"data parquet is missing columns: {sorted(missing)}")

    image_features = [
        name
        for name, feature in info.get("features", {}).items()
        if isinstance(feature, dict) and feature.get("dtype") in {"video", "image"}
    ]
    if image_features and not list((args.dataset / "videos").rglob("*.mp4")):
        return fail("image features are declared but no MP4 videos were written")

    print(
        "LeRobot output OK: "
        f"version={expected_version}, episodes={info['total_episodes']}, "
        f"frames={info['total_frames']}, fps={info.get('fps')}, "
        f"cameras={len(image_features)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
