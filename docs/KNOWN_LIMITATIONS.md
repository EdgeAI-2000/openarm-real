# Known limitations

## Startup and reproducibility

- The source deployment had no `.venv` or `.venv-dataset` at inspection time. These environments are deliberately excluded from Git; recreate them with `install.sh`.
- `run.sh bimanual` with the default Wi-Fi transport references `dataflow-jetson-bimanual.yaml`, which is absent from the source snapshot. USB bimanual files are present. This publication does not reconstruct the missing hardware dataflow.
- `constraints.txt` pins selected compute and driver versions but is not a complete lockfile. The `requirements-*.txt` files are historical environment records, not a guarantee of a reproducible fresh installation. Editable entries were made relative for publication.
- Hardware imports and local IK checks do not validate CAN ABI compatibility, bus mapping, zero positions or physical motion.
- The source directory had no top-level Git history. Upstream base revisions came from the old packaging manifest; newer local changes are part of this fresh source snapshot.

## Control

- Measured state is requested at 50 ms intervals and recorded, but the shipped real-robot dataflows do not connect measured state to the IK node's optional `position` input.
- The follower starts stopped unless explicitly requested otherwise. UI Start initializes the driver and invokes `arm.start()`; its exact motion semantics depend on the installed driver.
- Alignment limits each command to 0.001 rad by default and checks arm-joint alignment within 0.1 rad. Per-command limits are not equivalent to wall-clock velocity limits.
- The IK configuration supplies seven joint velocity limits and uses a nominal `dt=0.01`. Solve events are driven by incoming targets, not a guaranteed 100 Hz clock. Gripper targets pass through separately.
- The follower wrapper does not implement a target-age timeout, headset-disconnection stop, independent measured tracking-error guard or task-level collision checker.
- The follower's final stop is after the event loop, not protected by a `try/finally`. An exception can bypass that normal cleanup path. Lower-level driver behavior must be checked separately.
- UI stale-camera and VR-rate displays are monitoring information; they are not a motor-stop interlock.
- Use only one controller per CAN bus. This Dora driver path is separate from the ROS/MoveIt installation; it does not inherit the latter's trajectory-cancellation repair or other overlays.

## Data and cameras

- The recorder derives nominal frequencies by walking dataflow timer inputs. For event-driven IK this can record action frequency as 1 Hz even though action messages are triggered by target updates. Measure actual rates from timestamps.
- Camera timer settings do not prove achieved FPS. Overhead frames use Jetson reception time and include network delay; the camera streams are not hardware-synchronized.
- The optional D455 stream depends on an external sender, receiver and ROS bridge. Those services are not deployed by this repository.
- Local wrist camera fallback paths in `run.sh` use USB ports 4.4 (left) and 4.3 (right). They must match physical wiring; distinct device paths do not prove left/right identity.
- Conversion filters on recorded success/valid labels. Those labels do not independently prove task success. The validator may mark episodes invalid in the input metadata.
- Standard bimanual conversion requires both arms. Single-arm modes are for side-specific debugging, not the standard 16-dimensional training pipeline.

## Publication validation

The initial publication is checked for Python and shell syntax, referenced local configuration/model paths, repository payload size, excluded credentials/data, and content hashes. No dependency installation, real-camera capture, motor commands, full dataset conversion or end-to-end hardware acceptance test was performed as part of publication.
