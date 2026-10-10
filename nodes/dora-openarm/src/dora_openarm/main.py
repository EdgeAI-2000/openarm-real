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

"""Node to control OpenArm."""

import argparse
import dora
import openarm_driver
import pathlib
import pyarrow as pa
import numpy as np


QPOS_TYPE = pa.struct([("qpos", pa.list_(pa.float32()))])

STATE_TYPE = pa.struct(
    [
        ("qpos", pa.list_(pa.float32())),
        ("qvel", pa.list_(pa.float32())),
        ("qtorque", pa.list_(pa.float32())),
        ("tmos", pa.list_(pa.int32())),
        ("trotor", pa.list_(pa.int32())),
    ]
)


def build_qpos_output(qpos: np.ndarray) -> pa.Array:
    """Wrap a qpos array as a length-1 StructArray: [{"qpos": [...]}]."""
    return pa.array([{"qpos": qpos}], type=QPOS_TYPE)


def build_state_output(state) -> pa.Array:
    """Wrap a state dict as a length-1 StructArray: [{"qpos": [...], ...}]."""
    return pa.array(
        [
            {
                "qpos": state["qpos"],
                "qvel": state["qvel"],
                "qtorque": state["qtorque"],
                "tmos": state["tmos"],
                "trotor": state["trotor"],
            }
        ],
        type=STATE_TYPE,
    )


def extract_values(value: pa.Array, key: str) -> np.ndarray:
    """Read `key` from a length-1 StructArray, or a flat array as-is."""
    if pa.types.is_struct(value.type):
        value = value.field(key)[0].values
    return np.array(value, dtype=np.float32)


def main():
    """Move to the given position and output the current position."""
    parser = argparse.ArgumentParser(description="Control OpenArm")
    parser.add_argument(
        "--side",
        choices=["right", "left"],
        default="right",
        help="right or left",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="The configuration file for this OpenArm",
        type=pathlib.Path,
    )
    parser.add_argument(
        "--align-trigger",
        choices=["gripper"],
        default=None,
        help="Alignment trigger: gripper (default: None)",
    )
    parser.add_argument(
        "--align-threshold",
        default=0.1,
        help="Alignment threshold [rad] (default: 0.1)",
        type=float,
    )
    parser.add_argument(
        "--align-delta-limit",
        default=0.001,
        help="Maximum joint delta per alignment command [rad] (default: 0.001).",
        type=float,
    )
    parser.add_argument(
        "--align",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Align to incoming position commands after start (default: enabled).",
    )
    parser.add_argument(
        "--start-on-startup",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Start the arm on startup.",
    )
    parser.add_argument("--target-timeout", type=float, default=0.5,
                        help="Target/feedback timeout in seconds (default 0.5).")
    parser.add_argument("--tracking-error", type=float, default=0.35,
                        help="Maximum arm-joint tracking error in rad (default 0.35).")
    args = parser.parse_args()
    if args.align_delta_limit <= 0.0:
        parser.error("--align-delta-limit must be positive")
    from .session import Session, GuardFault
    import datetime
    import time

    node = dora.Node()
    name = f"{args.side}_arm"
    config = openarm_driver.Config(args.config)

    def emit(output, value):
        if output == "state":
            value = build_state_output(value)
        elif output == "action":
            value = build_qpos_output(value)
        else:
            value = pa.array([value])
        node.send_output(output, value, {"timestamp": time.time_ns()})

    session = Session(
        lambda: openarm_driver.SingleArmDriver(name, config), emit,
        side=args.side, align=args.align, align_trigger=args.align_trigger,
        threshold=args.align_threshold, align_step=args.align_delta_limit,
        timeout=args.target_timeout, tracking_error=args.tracking_error,
    )
    emit("status", "stopped")
    faulted_at = 0

    def event_age(event):
        stamp = event.get("metadata", {}).get("timestamp")
        if isinstance(stamp, datetime.datetime):
            stamp = stamp.timestamp() * 1_000_000_000
        age = float("inf") if stamp is None else (time.time_ns() - stamp) / 1e9
        return stamp, age

    try:
        if args.start_on_startup:
            session.start()
        while True:
            try:
                session.check_timeouts()
                event = node.next(timeout=0.02)
                if event is None or event["type"] == "STOP":
                    break
                if event["type"] == "ERROR" and event.get("error", "").startswith("Timeout event stream error:"):
                    continue
                if event["type"] == "ERROR":
                    raise RuntimeError(event.get("error", "Dora event error"))
                if event["type"] != "INPUT":
                    continue
                event_id = event["id"]
                if event_id == "peer_fault":
                    faulted_at = time.time_ns()
                    session.stop()
                elif event_id == "command":
                    command = event["value"][0].as_py()
                    if command == "start":
                        stamp, age = event_age(event)
                        if not np.isfinite(age) or age < -0.05 or age > args.target_timeout or stamp <= faulted_at:
                            print("Rejected stale Start command", flush=True)
                            continue
                        session.start()
                    elif command == "stop":
                        session.stop()
                elif event_id in ("request_state", "request_position"):
                    session.feedback()
                elif event_id == "move_position":
                    _, age = event_age(event)
                    session.target(extract_values(event["value"], "qpos"), age)
            except GuardFault as fault:
                print(f"Safety stop: {fault}", flush=True)
                faulted_at = time.time_ns()
                session.stop(fault)
    except BaseException as error:
        # Notify the other follower before final cleanup, even on driver failures.
        try:
            emit("safety_stop", f"follower failure: {type(error).__name__}")
        finally:
            raise
    finally:
        session.stop()


if __name__ == "__main__":
    main()
