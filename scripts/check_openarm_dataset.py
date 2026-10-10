#!/usr/bin/env python3
"""Check that selected OpenArm episodes have modalities needed by LeRobot."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from openarm_dataset import Dataset
from openarm_dataset.lerobot_v21 import _collect_keys_and_joint_names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--state", choices=("qpos", "pose", "rot6d"), default="qpos")
    parser.add_argument("--success-only", action="store_true")
    parser.add_argument("--valid-only", action="store_true")
    args = parser.parse_args()

    try:
        dataset = Dataset(args.dataset)
        episodes = list(dataset.meta.episodes)
        camera_names = list(dataset.camera_names)
        required_keys = set(_collect_keys_and_joint_names(dataset, args.state)[0])
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports library errors.
        print(f"Dataset metadata cannot be loaded: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    selected = []
    for episode in episodes:
        if args.success_only and not bool(episode.get("success", False)):
            continue
        if args.valid_only and not episode.valid():
            continue
        selected.append(episode)

    if not selected:
        errors.append("no episodes remain after success/valid filtering")

    for episode in selected:
        episode_id = str(episode["id"])
        label = f"episode {episode_id}"
        try:
            observations = dataset.load_obs(
                episode, use_unixtime=True, state=args.state
            )
            actions = dataset.load_action(
                episode, use_unixtime=True, state=args.state
            )
            cameras = dataset.load_cameras(episode)
        except Exception as exc:  # noqa: BLE001 - report the affected episode.
            errors.append(f"{label}: cannot load modalities: {exc}")
            continue

        if not observations:
            errors.append(f"{label}: no observation stream was recorded")
        if not actions:
            errors.append(f"{label}: no action stream was recorded")

        missing_observations = required_keys - set(observations)
        missing_actions = required_keys - set(actions)
        if missing_observations:
            errors.append(
                f"{label}: missing required observation keys "
                f"{sorted(missing_observations)}"
            )
        if missing_actions:
            errors.append(
                f"{label}: missing required action keys {sorted(missing_actions)}"
            )

        starts: list[float] = []
        ends: list[float] = []
        for kind, streams in (("observation", observations), ("action", actions)):
            for name, frame in streams.items():
                if frame.empty:
                    errors.append(f"{label}: {kind} stream {name!r} is empty")
                    continue
                starts.append(float(frame.index[0]))
                ends.append(float(frame.index[-1]))

        for camera_name in camera_names:
            camera = cameras.get(camera_name)
            timestamps = camera.load_timestamps() if camera is not None else []
            if not timestamps:
                errors.append(f"{label}: camera {camera_name!r} has no frames")
                continue
            starts.append(float(timestamps[0]))
            ends.append(float(timestamps[-1]))

        if starts and ends:
            overlap = min(ends) - max(starts)
            if not math.isfinite(overlap) or overlap <= 0:
                errors.append(f"{label}: modalities have no common timestamp interval")

    if errors:
        print("LeRobot conversion preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"Preflight OK: {len(selected)} episode(s), "
        f"{len(camera_names)} camera stream(s), state={args.state}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
