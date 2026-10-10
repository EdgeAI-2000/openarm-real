#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
mode="${1:-core}"
case "$mode" in core|hardware|dataset) ;; *) echo 'Usage: bash install.sh core|hardware|dataset' >&2; exit 2;; esac
if [[ "$mode" != dataset && "$(uname -m)" != aarch64 ]]; then
    echo 'This installer is intended for the ARM64 Jetson.' >&2; exit 1
fi
uv_bin="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "$uv_bin" && -x .venv/bin/uv ]]; then
    uv_bin="$(pwd)/.venv/bin/uv"
fi
[[ -n "$uv_bin" && -x "$uv_bin" ]] || {
    echo 'Install uv or set UV_BIN to its executable path; see README.md.' >&2
    exit 1
}
if [[ "$mode" == dataset ]]; then
    command -v ffmpeg >/dev/null || {
        echo 'Install ffmpeg first (Ubuntu: sudo apt install ffmpeg).' >&2
        exit 1
    }
    if [[ ! -x .venv-dataset/bin/python ]]; then
        "$uv_bin" venv --python 3.12 .venv-dataset
    fi
    # The official converter writes v3 Parquet/MP4 directly. Installing the
    # optional LeRobot extra here would pull training/runtime dependencies that
    # are unnecessary for conversion (and problematic on ARM64).
    openarm_dataset_commit=a69fe37384e26bb5c3059de4a52cd6e871727011
    "$uv_bin" pip install --python .venv-dataset/bin/python \
        "openarm_dataset @ git+https://github.com/enactic/openarm_dataset.git@$openarm_dataset_commit"
    "$uv_bin" pip check --python .venv-dataset/bin/python
    "$uv_bin" pip freeze --python .venv-dataset/bin/python > requirements-dataset.txt
    .venv-dataset/bin/openarm-dataset-convert --help >/dev/null
    echo 'Dataset conversion environment installed in .venv-dataset.'
    exit 0
fi
if [[ ! -x .venv/bin/python ]]; then "$uv_bin" venv --python 3.12 .venv; fi
if [[ "$mode" == core ]]; then
    "$uv_bin" pip install --python .venv/bin/python -c constraints.txt \
        dora-rs-cli -e openarm_mujoco -e openarm_control \
        -e dora-openarm-data-collection/nodes/dora-openarm-stereo-camera \
        -e dora-openarm-data-collection/nodes/dora-openarm-webxr \
        -e dora-openarm-data-collection/nodes/dora-openarm-kinematics \
        -e dora-openarm-data-collection/nodes/dora-openarm-data-collection-ui \
        -e dora-openarm-data-collection/nodes/dora-openarm-quitter \
        -e dora-openarm-data-collection/nodes/dora-openarm-dataset-recorder
else
    "$uv_bin" pip install --python .venv/bin/python -c constraints.txt \
        -e dora-openarm-data-collection/nodes/dora-openarm
    .venv/bin/python -c 'import openarm_driver, openarm_can; print("Hardware imports OK; no motor connection attempted")'
fi
"$uv_bin" pip check --python .venv/bin/python
"$uv_bin" pip freeze --python .venv/bin/python > "requirements-jetson-${mode}.txt"
echo 'Installed. No CAN configuration or motor startup was performed.'
