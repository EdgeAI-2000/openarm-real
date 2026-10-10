# Copyright 2026 Enactic, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Node to record data from OpenArm and cameras as OpenArm dataset."""

import argparse
from dataclasses import dataclass, field
import datetime
import copy
import dora
import json
import os
import pathlib
import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np
import math
from numpy.typing import ArrayLike
import shutil
import yaml


@dataclass
class Episode:
    """Episode related data."""

    number: int = 0
    success: bool = False
    task_index: int = 0

    camera_timestamps: dict = field(default_factory=dict)

    right_action_timestamps: ArrayLike = field(default_factory=list)
    right_actions: ArrayLike = field(default_factory=list)
    right_observation_timestamps: ArrayLike = field(default_factory=list)
    right_observations: ArrayLike = field(default_factory=list)
    left_action_timestamps: ArrayLike = field(default_factory=list)
    left_actions: ArrayLike = field(default_factory=list)
    left_observation_timestamps: ArrayLike = field(default_factory=list)
    left_observations: ArrayLike = field(default_factory=list)
    elevation_action_timestamps: ArrayLike = field(default_factory=list)
    elevation_actions: ArrayLike = field(default_factory=list)
    elevation_observation_timestamps: ArrayLike = field(default_factory=list)
    elevation_observations: ArrayLike = field(default_factory=list)


def extract_values(value: pa.Array, key: str) -> np.ndarray:
    """Read `key` from a length-1 StructArray, or a flat array as-is."""
    if pa.types.is_struct(value.type):
        value = value.field(key)[0].values
    return np.array(value, dtype=np.float32)


class EpisodeWriter:
    """Writer an episode."""

    def __init__(self, directory, episode):
        """Initialize variables."""
        self._directory = directory
        self._episode = episode
        self._base_directory = self._directory / "episodes" / str(self._episode.number)

    def write_camera_image(self, name, image, timestamp, format):
        """Write an image from a camera."""
        output_path = self._base_directory / "cameras" / name / f"{timestamp}.{format}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as output:
            # Using pa.PythonFile here is for zero-copy. We can't
            # write pa.Buffer data to Python's IO directory. If we use
            # Python's IO, we need to copy data in pa.Buffer as
            # Python's bytes. We want to avoid it.
            with pa.PythonFile(output) as pa_output:
                pa_output.write(image.buffers()[1])

    def finish(self):
        """Write all pending data."""
        if self._episode.right_actions:
            self._write_kinematic_state(
                self._base_directory / "action" / "arms" / "right",
                self._episode.right_action_timestamps,
                self._episode.right_actions,
            )
        if self._episode.right_observations:
            self._write_kinematic_state(
                self._base_directory / "obs" / "arms" / "right",
                self._episode.right_observation_timestamps,
                self._episode.right_observations,
            )
        if self._episode.left_actions:
            self._write_kinematic_state(
                self._base_directory / "action" / "arms" / "left",
                self._episode.left_action_timestamps,
                self._episode.left_actions,
            )
        if self._episode.left_observations:
            self._write_kinematic_state(
                self._base_directory / "obs" / "arms" / "left",
                self._episode.left_observation_timestamps,
                self._episode.left_observations,
            )
        if self._episode.elevation_actions:
            self._write_positions(
                self._base_directory / "action" / "lifter" / "elevation.parquet",
                self._episode.elevation_action_timestamps,
                self._episode.elevation_actions,
            )
        if self._episode.elevation_observations:
            self._write_positions(
                self._base_directory / "obs" / "lifter" / "elevation.parquet",
                self._episode.elevation_observation_timestamps,
                self._episode.elevation_observations,
            )

    def cancel(self):
        """Cancel this episode."""
        shutil.rmtree(self._base_directory, ignore_errors=True)

    def _write_positions(self, output_path, timestamps, positions):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_type = pa.list_(pa.float32())
        table = pa.table(
            {
                "timestamp": pa.array(timestamps, type=pa.timestamp("ns")),
                "value": pa.array(positions, type=list_type),
            }
        )
        pq.write_table(table, output_path)

    def _write_kinematic_state(self, base_path, timestamps, states):
        output_path = base_path / "state.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        list_type = pa.list_(pa.float32())
        first = states[0]

        if isinstance(first, pa.StructArray):
            field_names = first.type.names
            available_field_names = [
                "qpos",
                "qvel",
                "qtorque",
                "pose",
            ]  # currently only support these fields
            state_fields = {"timestamp": pa.array(timestamps, type=pa.timestamp("ns"))}
            for field_name in field_names:
                if field_name not in available_field_names:
                    continue
                state_fields[field_name] = pa.array(
                    [extract_values(s, field_name) for s in states],
                    type=list_type,
                )
            table = pa.table(state_fields)
        else:
            # if the observation is not a struct, it should be qpos.
            table = pa.table(
                {
                    "timestamp": pa.array(timestamps, type=pa.timestamp("ns")),
                    "qpos": pa.array(states, type=list_type),
                }
            )
        pq.write_table(table, output_path)


class DatasetWriter:
    """Write a dataset."""

    _VERSION = "0.4.0"

    def __init__(self, directory, name, metadata):
        """Initialize variables."""
        self._directory = directory
        self._name = name
        self._metadata = metadata
        self._base_directory = self._directory / name
        self._episode_results = []
        if self._base_directory.exists():
            existing = self._read_existing_metadata()
            if existing is not None:
                mismatched = {
                    k: v
                    for k, v in self._metadata.items()
                    if k in existing and existing[k] != v
                }
                if mismatched:
                    raise ValueError(
                        f"Existing dataset metadata does not match: {self._base_directory / 'metadata.yaml'}\n"
                        + "\n".join(
                            f"  {k}: existing={existing.get(k)!r}, current={v!r}"
                            for k, v in mismatched.items()
                        )
                    )
        else:
            self._base_directory.mkdir(parents=True)

    def create_episode_writer(self, episode):
        """Create a writer for the given episode."""
        episode_id = str(episode.number)
        if episode_id in {result["id"] for result in self._episode_results}:
            raise ValueError(f"Episode {episode_id} already exists in dataset")
        episode_directory = self._base_directory / "episodes" / episode_id
        if episode_directory.exists():
            raise ValueError(f"Episode directory already exists: {episode_directory}")
        return EpisodeWriter(self._base_directory, episode)

    def finish_episode(self, episode):
        """Add a finished episode to the writer."""
        self._episode_results.append(
            dict(
                id=str(episode.number),
                success=episode.success,
                task_index=episode.task_index,
                measured_frequencies=episode_frequencies(episode),
            )
        )
        self._write_metadata_file()

    def set_leader_ker_metadata(self, ker_metadata):
        """Record KER leader device metadata under equipment.leader.ker."""
        equipment = self._metadata.setdefault("equipment", {})
        leader = equipment.setdefault("leader", {})
        ker = leader.setdefault("ker", {})
        ker["id"] = "OpenArmKER"
        ker["firmware_version"] = ker_metadata.get("fw")
        ker["hardware_version"] = ker_metadata.get("hw")
        self._write_metadata_file()

    def _write_metadata_file(self):
        metadata = copy.deepcopy(self._metadata)
        metadata["version"] = self._VERSION
        metadata["episodes"] = self._episode_results
        output_path = self._base_directory / "metadata.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True)

    def _read_existing_metadata(self):
        metadata_path = self._base_directory / "metadata.yaml"
        if not metadata_path.exists():
            return None
        with open(metadata_path, encoding="utf-8") as f:
            existing_metadata = yaml.safe_load(f) or {}
        self._episode_results = existing_metadata.get("episodes", [])
        return existing_metadata


def measured_hz(timestamps):
    """Mean rate over a strictly increasing timestamp series; unknown if sparse."""
    values = np.asarray(timestamps, dtype=np.int64)
    if len(values) < 2 or np.any(np.diff(values) <= 0):
        return None
    return float((len(values) - 1) * 1e9 / (values[-1] - values[0]))


def episode_frequencies(episode):
    frequencies = {"action": {"arms": {}}, "obs": {"arms": {}}, "cameras": {}}
    for side in ("left", "right"):
        for kind, prefix in (("action", "action"), ("obs", "observation")):
            stamps = getattr(episode, f"{side}_{prefix}_timestamps")
            if len(stamps):
                frequencies[kind]["arms"][side] = measured_hz(stamps)
    frequencies["cameras"] = {name: measured_hz(stamps) for name, stamps in episode.camera_timestamps.items()}
    return frequencies


class FrequencyDetector:
    """Report nominal rates only for directly timer-triggered outputs."""

    def __init__(self, configs):
        self._configs = configs

    def detect(self, source):
        return self._detect(source, set())

    def _detect(self, source, visited):
        if isinstance(source, dict):
            source = source["source"]
        if source in visited:
            return None
        visited.add(source)
        node_id, output = source.split("/", 1)
        config = next((c for c in self._configs if c["id"] == node_id), None)
        if config is None:
            return None
        inputs = config["inputs"]
        # Action is driven by incoming commands; IK is driven by target events.
        if output in ("action", "position_left", "position_right"):
            return None
        if node_id.startswith("overhead"):
            return None  # A network poll timer is not its source frame rate.
        timer = inputs.get("request_state") or inputs.get("request_position") or inputs.get("tick")
        if isinstance(timer, dict):
            timer = timer["source"]
        if not timer:
            return None
        if not timer.startswith("dora/timer/"):
            return self._detect(timer, visited)
        unit, value = timer.split("/")[2:4]
        return {"secs": 1.0, "millis": 1000.0}.get(unit, 0) / int(value)


def _collect_dynamic_metadata(metadata, args, node):
    metadata["operation_type"] = args.operation_type
    if args.operation_type == "teleop":
        if "equipment" not in metadata:
            metadata["equipment"] = {}
        if "embodiments" not in metadata["equipment"]:
            metadata["equipment"]["embodiments"] = {}
        # equipment.leader.ker is filled at runtime from the KER node's
        # metadata reply (see main()'s "ker_metadata" handling).
    elif args.operation_type == "rollout":
        if "model" not in metadata:
            metadata["model"] = {}
        if args.docker_image:
            metadata["model"]["docker_image"] = args.docker_image

    metadata["frequencies"] = {
        "action": {
            "arms": {},
        },
        "obs": {
            "arms": {},
        },
        "cameras": {},
    }
    frequency_detector = FrequencyDetector(node.dataflow_descriptor()["nodes"])
    for name, input in node.node_config()["inputs"].items():
        frequency = frequency_detector.detect(input)
        if not frequency:
            continue
        if name.startswith("arm_"):
            # arm_right_action -> right, action
            side, type = name.split("_")[1:3]
            if type == "observation":
                type = "obs"
            metadata["frequencies"][type]["arms"][side] = frequency
        elif name.startswith("camera_"):
            # camera_wrist_right -> wrist_right
            camera_name = name.removeprefix("camera_")
            metadata["frequencies"]["cameras"][camera_name] = frequency


def main():
    """Collect data and record them."""
    parser = argparse.ArgumentParser(description="Record data as OpenArm dataset")
    parser.add_argument(
        "--directory",
        default=os.getenv("DIRECTORY", os.getcwd()),
        help="The output directory",
        type=pathlib.Path,
    )
    parser.add_argument(
        "--docker-image",
        default=os.getenv("DOCKER_IMAGE", os.getenv("IMAGE")),
        help="The Docker image used for this rollout",
        type=str,
    )
    parser.add_argument(
        "--metadata-file",
        default=os.getenv("METADATA_FILE"),
        help="The metadata file",
        type=pathlib.Path,
    )
    parser.add_argument(
        "--name",
        default=os.getenv("NAME", "dataset"),
        help="The dataset name",
        type=str,
    )
    parser.add_argument(
        "--operation-type",
        choices=["teleop", "rollout"],
        default=os.getenv("OPERATION_TYPE", "teleop"),
        help="The operation type",
        type=str,
    )
    args = parser.parse_args()

    node = dora.Node()
    if args.metadata_file is None:
        metadata = {}
    else:
        with open(args.metadata_file, encoding="utf-8") as f:
            metadata = yaml.safe_load(f)
    _collect_dynamic_metadata(metadata, args, node)
    dataset_writer = DatasetWriter(args.directory, args.name, metadata)
    episode = None
    episode_writer = None

    for event in node:
        if event["type"] != "INPUT":
            continue

        event_id = event["id"]
        if event_id == "command":
            command = event["value"][0].as_py()
            if command == "start":
                episode = Episode()
                episode.number = event["metadata"].get("episode_number", 0)
                episode.task_index = event["metadata"].get("task_index", 0)
                episode_writer = dataset_writer.create_episode_writer(episode)
            elif command in ("success", "fail"):
                if command == "success":
                    episode.success = True
                episode_writer.finish()
                dataset_writer.finish_episode(episode)
                episode = None
                episode_writer = None
            elif command == "cancel":
                episode_writer.cancel()
                episode = None
                episode_writer = None
            elif command == "quit":
                if episode is not None:
                    episode_writer.finish()
                    dataset_writer.finish_episode(episode)
                    episode = None
                    episode_writer = None
                break
            continue

        if event_id == "ker_metadata":
            # KER leader device metadata (JSON) from the KER node.
            ker_metadata = json.loads(event["value"][0].as_py())
            dataset_writer.set_leader_ker_metadata(ker_metadata)
            continue

        # Main process
        if episode is None:
            continue
        timestamp = event["metadata"]["timestamp"]
        if isinstance(timestamp, datetime.datetime):
            # Added by dora-rs automatically.
            # Convert to POSIX timestamp in nanosecond.
            timestamp = math.ceil(timestamp.timestamp() * 1_000_000_000)
        if event_id.startswith("arm_"):
            value = event["value"]
            if isinstance(value, pa.StructArray) and "new_position" in value.type.names:
                value = value.field("new_position")

            # arm_right_action ->
            # right_action
            key_prefix = event_id.removeprefix("arm_")
            # right_action ->
            # right_actions
            values_key = f"{key_prefix}s"
            getattr(episode, values_key).append(value)
            # right_action ->
            # right_action_timestamps
            timestamps_key = f"{key_prefix}_timestamps"
            getattr(episode, timestamps_key).append(timestamp)
        elif event_id.startswith("elevation_"):
            # elevation_observation -> elevation_observations, elevation_observation_timestamps
            # elevation_action -> elevation_actions, elevation_action_timestamps
            getattr(episode, f"{event_id}s").append(event["value"])
            getattr(episode, f"{event_id}_timestamps").append(timestamp)
        elif event_id.startswith("camera_"):
            name = event_id.removeprefix("camera_")
            image = event["value"]
            format = event["metadata"]["encoding"]
            episode_writer.write_camera_image(name, image, timestamp, format)
            episode.camera_timestamps.setdefault(name, []).append(timestamp)


if __name__ == "__main__":
    main()
