# Deployment and collection

## 1. Install the core environment

The robot target is Jetson AGX Orin, Ubuntu 22.04, aarch64. Install `uv`, then run from the repository root:

```bash
bash install.sh core
.venv/bin/python preflight.py
```

The installer creates a private Python 3.12 `.venv`. Core mode installs Dora, the editable model/control packages, WebXR, IK, cameras, UI, quitter and recorder. It does not configure CAN or start motors. `preflight.py` runs an IK benchmark without connecting to CAN.

## 2. Connect Quest over USB (default)

Install ADB and enable Quest developer mode and USB debugging. Connect the headset with a data-capable cable, accept the debugging authorization, then inspect:

```bash
adb devices
ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
```

The head input must be a side-by-side UVC stereo image, configured at 2560×720 at 30 FPS. The script prefers `/dev/camera_head_stereo`, falling back to the configured ZED-M by-id path. Each wrist camera is configured at 960×600 at 30 FPS.

Override camera paths for your own wiring:

```bash
export STEREO_CAMERA_DEVICE=/dev/v4l/by-id/YOUR_STEREO_CAMERA
export WRIST_CAMERA_LEFT_DEVICE=/dev/v4l/by-path/YOUR_LEFT_WRIST_CAMERA
export WRIST_CAMERA_RIGHT_DEVICE=/dev/v4l/by-path/YOUR_RIGHT_WRIST_CAMERA
bash run.sh check usb-stereo
```

Do not run competing processes on the same cameras. Check mode has no motor follower and does not record. The script adds ADB reverse forwarding for port 8443, waits for the headset to wake, opens the WebXR page and attempts to enter XR. If automatic entry fails, press Start in the headset.

`QUEST_USB_WAKE_TIMEOUT` defaults to 0 (wait indefinitely). Set a positive number of seconds to bound the wait. USB WebXR listens on `127.0.0.1:8443` without TLS; the headset reaches it through ADB reverse.

## 3. Open the UI from another computer

Replace the example host and username with your Jetson details:

```bash
export JETSON_HOST=jetson.local
export JETSON_USER=your-user
ssh -F none -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18000:127.0.0.1:8000 \
  "${JETSON_USER}@${JETSON_HOST}"
```

Keep the SSH session open and visit `http://127.0.0.1:18000/`. The read-only camera preview is at `/monitor`; it reuses the UI's received JPEG frames rather than opening cameras again. Confirm camera orientation, left/right identity, controller tracking and changing IK targets before proceeding.

Camera geometry and view comfort require calibration. `config/view_camera_stereo.yaml` is a deployment example, not a calibration for every robot. The ZED view-parameter utility is under `nodes/dora-openarm-webxr/example/`.

## 4. Wi-Fi alternative

Wi-Fi mode requires a locally generated TLS certificate. No certificate or private key is shipped. Use the actual Jetson IP in both the CN and Subject Alternative Name:

```bash
export JETSON_IP=192.0.2.70  # Replace with your actual address.
mkdir -p config/tls
test ! -e config/tls/server.key && test ! -e config/tls/server.crt && (
  umask 077
  openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout config/tls/server.key -out config/tls/server.crt \
    -subj "/CN=${JETSON_IP}" \
    -addext "subjectAltName=IP:${JETSON_IP},DNS:localhost,IP:127.0.0.1"
)
bash run.sh check wifi
```

Open `https://YOUR_JETSON_IP:8443/` in Quest. Set `JETSON_HOST` to print your own headset URL. Wi-Fi modes do not record cameras; the Wi-Fi bimanual dataflow records both arms.

## 5. Hardware environment and onsite checks

Install a matching OpenArm CAN C++ library and tools before:

```bash
bash install.sh hardware
```

The hardware installer only installs/imports bindings. It does not enable motors. Driver/CAN versions are pinned in `constraints.txt` and still require verification against the actual installation.

Keep the existing verified CAN configuration. Do not reset zero positions or run a generic interface-reconfiguration tool. Verify bus-to-arm identity, motor IDs, zero positions, units, initial pose, gripper range and physical emergency stop. End other hardware-control sessions normally before using this path.

With onsite supervision and the checks completed, robot-mode entrypoints are:

```bash
bash run.sh right usb-stereo
bash run.sh left usb-stereo
bash run.sh bimanual usb-stereo
```

Test each side separately before bimanual operation. The UI Arm Start command starts the driver and may execute the initial-position movement. Hold the corresponding controller trigger for alignment; alignment itself moves the robot. Wait for `aligned` before normal following. Releasing the trigger controls the gripper, not a dead-man motor-enable switch.

Software Stop or normal exit may use a stopping trajectory. Neither is an immediate physical emergency stop. See [known limitations](KNOWN_LIMITATIONS.md) before physical operation.

## 6. Optional D455 overhead camera

```bash
bash run.sh check usb-stereo d455
# After checks and onsite hardware preparation:
bash run.sh bimanual usb-stereo d455
```

The fifth image stream subscribes to existing ROS JPEG messages at `/overhead/color/image_raw/compressed` through `ws://127.0.0.1:9091`. Set `OVERHEAD_ROSBRIDGE_URL` and `OVERHEAD_IMAGE_TOPIC` to override these values. The external network sender, receiver and ROS bridge must already be running; this repository does not install them.

The overhead node preserves the source JPEG and uses Jetson reception timestamps. It waits for new frames, checks timestamps and reports missing/stale frames. Its 33 ms poll timer does not imply a 30 FPS upstream source. Depth and point clouds are not recorded by this stream.

## 7. Record episodes

Edit the task prompt in `metadata_real_stereo.yaml`, or `metadata_real_stereo_d455.yaml` for five-camera mode. Keep task semantics consistent between collection and training.

Robot modes create a unique directory under `dora-openarm-data-collection/real_data/`. Motor Start/Stop and episode recording are separate controls:

1. Confirm both arms' state and every configured camera stream are updating.
2. Right-controller A while idle starts an episode.
3. A while recording marks success; B marks failure.
4. B while idle exits collection.

Each episode contains `action/`, `obs/` and `cameras/`. Do not classify empty startup directories without `metadata.yaml` as datasets. Record a few short samples and check them before collecting a large batch.

## 8. Convert data

Install system `ffmpeg` before creating the separate conversion environment:

```bash
bash install.sh dataset
bash convert.sh \
  dora-openarm-data-collection/real_data/YOUR_DATASET \
  lerobot_data/YOUR_NEW_OUTPUT
```

The converter is pinned to upstream `openarm_dataset` commit `a69fe37384e26bb5c3059de4a52cd6e871727011`. It writes Parquet and MP4 without installing LeRobot training dependencies. Dataset installation does not require Jetson/aarch64, so conversion can be moved to a Python 3.12 Linux workstation.

The wrapper runs modality/time-overlap checks, the upstream validator, conversion and output verification. Defaults exclude failed and invalid episodes. The upstream validator can update input metadata; keep raw backups. Output paths must be new.

Run `bash convert.sh` without arguments to view supported environment overrides. Do not loosen validity thresholds solely to force bad episodes through conversion.

## Runtime guards

The follower checks target and feedback freshness with a default 0.5 s timeout, validates finite eight-value vectors, and compares measured arm joints with the last sent command (default 0.35 rad maximum error). These parameters are configurable with `--target-timeout` and `--tracking-error` in follower arguments. Their defaults require onsite validation.

Every sent command is limited using monotonic elapsed time, capped at a 50 ms allowance: seven arm limits `[2, 2, 3.14, 3.14, 6.3, 6.3, 6.3]` rad/s and a gripper command limit of 0.5 rad/s. These bounds apply to position-command changes, not measured physical velocity. Startup/stop movements are still owned by the driver.

After a guard fault, the session stops and remains stopped until a fresh manual Arm Start. In bimanual mode a fault requests stop from the other follower. Driver exceptions trigger peer notification and final cleanup. Blocking driver calls, lost power or a process kill cannot be handled by the Python watchdog; the physical emergency stop remains necessary.

IK requires fresh feedback and fresh controller targets for every active side. The oldest contributing controller timestamp is preserved for follower freshness checks. Dataset action fields now record the limited commands sent by each follower; each episode also saves rates measured from its timestamps.
