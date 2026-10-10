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

"""Dora node: mink-based differential IK solver for OpenArm.

Accepts end-effector pose targets and solves joint angles via mink's QP-based
differential IK. Both arms share one mink.Configuration and one QP solve per
step.

Pose convention:  float32[8] = [px, py, pz, qw, qx, qy, qz, gripper_angle]
Inputs:
  target_right – [{"pose": float32[8]}]  right EE target pose + gripper angle
  target_left  – [{"pose": float32[8]}]  left  EE target pose + gripper angle
  position     – [{"qpos": float32[16]}] current joint state right[8]+left[8]
                 (optional sync)
  Flat float32 arrays are also accepted for all inputs.

Outputs:
  position_right – [{"qpos": float32[8]}] solved right arm joint angles
  position_left  – [{"qpos": float32[8]}] solved left arm joint angles
  status         – ["ready"] on startup
"""

from __future__ import annotations

import argparse
import datetime
import time

import dora
import numpy as np
import pyarrow as pa

from openarm_control import (
    Kinematics,
    register_common_args,
    register_ik_args,
    ik_params_from_args,
    setup_from_args,
)


_QPOS_STRUCT_TYPE = pa.struct({"qpos": pa.list_(pa.float32())})


def build_qpos_output(qpos: np.ndarray) -> pa.Array:
    """Wrap joint angles as a length-1 StructArray: [{"qpos": [...]}]."""
    return pa.array([{"qpos": qpos}], type=_QPOS_STRUCT_TYPE)


def extract_values(value: pa.Array, key: str) -> np.ndarray:
    """Read `key` from a length-1 StructArray, or a flat array as-is."""
    if pa.types.is_struct(value.type):
        value = value.field(key)[0].values
    return np.array(value, dtype=np.float32)


def timestamp_ns(metadata):
    stamp = metadata.get("timestamp")
    if isinstance(stamp, datetime.datetime):
        return int(stamp.timestamp() * 1e9)
    return stamp


def fresh(stamp, now, timeout):
    return stamp is not None and np.isfinite(stamp) and -0.05 <= (now - stamp) / 1e9 <= timeout


def _run(args: argparse.Namespace) -> None:
    kin = Kinematics(setup_from_args(args), ik_params_from_args(args))
    node = dora.Node()
    node.send_output("status", pa.array(["ready"]))
    feedback = {}
    targets = {}
    for event in node:
        if event["type"] != "INPUT":
            continue
        eid = event["id"]
        stamp = timestamp_ns(event["metadata"])
        now = time.time_ns()
        if eid.startswith("feedback_"):
            side = eid.removeprefix("feedback_")
            values = extract_values(event["value"], "qpos")
            if side in kin.setup.sides:
                if values.shape == (8,) and np.isfinite(values).all() and fresh(stamp, now, args.input_timeout):
                    feedback[side] = (values, stamp)
                else:
                    feedback.pop(side, None)
            continue
        if eid == "position":
            values = extract_values(event["value"], "qpos")
            if values.shape == (16,) and np.isfinite(values).all() and fresh(stamp, now, args.input_timeout):
                kin.sync(values)
            continue
        if not eid.startswith("target_"):
            continue
        side = eid.removeprefix("target_")
        if side not in kin.setup.sides:
            continue
        values = extract_values(event["value"], "pose")
        if values.shape != (8,) or not np.isfinite(values).all() or not fresh(stamp, now, args.input_timeout):
            targets.pop(side, None)
            continue
        kin.set_target(side, values[:7])
        kin.set_gripper(side, values[7])
        targets[side] = stamp
        if not kin.ready() or not all(fresh(targets.get(s), now, args.input_timeout) for s in kin.setup.sides):
            continue
        if args.require_feedback:
            if not all(s in feedback and fresh(feedback[s][1], now, args.input_timeout) for s in kin.setup.sides):
                continue
            measured = np.zeros(16, dtype=np.float32)
            for s in kin.setup.sides:
                offset = 0 if s == "right" else 8
                measured[offset:offset + 8] = feedback[s][0]
            kin.sync(measured)
            kin.update_measured_state(measured)
        result = kin.solve()
        if result is None or not np.isfinite(result).all():
            continue
        # Keep the oldest contributing controller timestamp. Solver delay and an
        # absent controller must not make stale poses appear fresh downstream.
        metadata = {"timestamp": min(targets[s] for s in kin.setup.sides)}
        for s in kin.setup.sides:
            offset = 0 if s == "right" else 8
            node.send_output("position_" + s, build_qpos_output(result[offset:offset + 8]), metadata)


def main() -> None:
    """Inverse kinematics for OpenArm."""
    parser = argparse.ArgumentParser(
        description="Mink IK dora node – OpenArm end-effector pose → joint angles"
    )
    register_common_args(parser)
    register_ik_args(parser)
    parser.add_argument("--require-feedback", action="store_true")
    parser.add_argument("--input-timeout", type=float, default=0.5)
    args = parser.parse_args()
    if not np.isfinite(args.input_timeout) or args.input_timeout <= 0:
        parser.error("--input-timeout must be finite and positive")
    _run(args)


if __name__ == "__main__":
    main()
