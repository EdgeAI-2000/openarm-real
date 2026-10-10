"""Bounded teleoperation session; no hardware is constructed on import."""

import time
import numpy as np


class GuardFault(RuntimeError):
    """A command, feedback or timing check failed."""


def vector(values):
    q = np.asarray(values, dtype=np.float64)
    if q.shape != (8,) or not np.isfinite(q).all():
        raise GuardFault("expected eight finite joint/gripper values")
    return q


class Session:
    """Latch faults until an explicit new Start; serialize all driver calls."""

    def __init__(self, factory, emit, *, side, align=True, align_trigger=None,
                 threshold=0.1, align_step=0.001, timeout=0.5,
                 tracking_error=0.35, clock=time.monotonic):
        if not all(np.isfinite(v) and v > 0 for v in
                   (threshold, align_step, timeout, tracking_error)):
            raise ValueError("guard thresholds must be finite and positive")
        self.factory, self.emit, self.side = factory, emit, side
        self.align, self.align_trigger = align, align_trigger
        self.threshold, self.align_step = threshold, align_step
        self.timeout, self.tracking_error, self.clock = timeout, tracking_error, clock
        self.arm = None
        self.status = "stopped"
        self.last_target = self.last_feedback = self.last_send = None
        self.sent = None
        self.caps = np.array([2.0, 2.0, 3.14, 3.14, 6.3, 6.3, 6.3, 0.5])

    def start(self):
        if self.arm is not None:
            return  # Repeated Start must not recreate or reposition an active arm.
        self.arm = self.factory()
        self.arm.start()
        self.sent = vector(self.arm.fetch_position(refresh=True)).copy()
        now = self.clock()
        self.last_target = self.last_feedback = self.last_send = now
        self.status = "started" if self.align else "aligned"
        self.emit("status", self.status)

    def stop(self, fault=None):
        # Keep the object if stop raises, so final cleanup can retry it.
        if self.arm is not None:
            self.arm.stop()
            self.arm = None
        self.status = "stopped"
        self.emit("status", self.status)
        if fault:
            self.emit("safety_stop", str(fault))

    def check_timeouts(self):
        if self.arm is None:
            return
        now = self.clock()
        if now - self.last_target > self.timeout:
            raise GuardFault("controller target timeout")
        if now - self.last_feedback > self.timeout:
            raise GuardFault("joint feedback timeout")

    def feedback(self):
        if self.arm is None:
            return
        state = self.arm.fetch_state(refresh=True)
        measured = vector(state["qpos"])
        # Check arm joints; gripper units/signs differ across driver versions.
        if np.max(np.abs(measured[:7] - self.sent[:7])) > self.tracking_error:
            raise GuardFault("measured joint position differs from sent target")
        self.last_feedback = self.clock()
        self.emit("state", state)

    def target(self, values, age):
        if self.arm is None:
            return
        target = vector(values)
        if not np.isfinite(age) or age < -0.05 or age > self.timeout:
            raise GuardFault("stale or invalid controller target timestamp")
        self.last_target = self.clock()
        dt = max(0.0, min(self.last_target - self.last_send, 0.05))
        if self.status == "started":
            if self.align_trigger == "gripper":
                gripping = target[-1] > np.deg2rad(-5) if self.side == "right" else target[-1] < np.deg2rad(5)
                if not gripping:
                    return
            current = vector(self.arm.fetch_position(refresh=True))
            if np.max(np.abs(current[:7] - target[:7])) < self.threshold:
                self.status = "aligned"
                self.emit("status", self.status)
            else:
                target = self.sent + np.clip(target - self.sent, -self.align_step, self.align_step)
        # A wall-clock bound covers all eight outputs, including the gripper.
        command = self.sent + np.clip(target - self.sent, -self.caps * dt, self.caps * dt)
        self.arm.send_position(command)
        self.sent = command.copy()
        self.last_send = self.last_target
        self.emit("action", command)
