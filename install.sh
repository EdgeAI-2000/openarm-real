#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
mode="${1:-core}"
case "$mode" in core|hardware|dataset) ;; *) echo 'Usage: bash install.sh core|hardware|dataset' >&2; exit 2;; esac
if [[ "$mode" != dataset && "$(uname -m)" != aarch64 ]]; then
    echo 'This installer is intended for the ARM64 Jetson.' >&2; exit 1
fi
command -v uv >/dev/null || { echo 'Install uv first; see README.md.' >&2; exit 1; }
if [[ "$mode" == dataset ]]; then
    command -v ffmpeg >/dev/null || {
        echo 'Install ffmpeg first (Ubuntu: sudo apt install ffmpeg).' >&2
        exit 1
    }
    if [[ ! -x .venv-dataset/bin/python ]]; then
        uv venv --python 3.12 .venv-dataset
    fi
    # The official converter writes v3 Parquet/MP4 directly. Installing the
    # optional LeRobot extra here would pull training/runtime dependencies that
    # are unnecessary for conversion (and problematic on ARM64).
    openarm_dataset_commit=a69fe37384e26bb5c3059de4a52cd6e871727011
    uv pip install --python .venv-dataset/bin/python \
        "openarm_dataset @ git+https://github.com/enactic/openarm_dataset.git@$openarm_dataset_commit"
    uv pip check --python .venv-dataset/bin/python
    uv pip freeze --python .venv-dataset/bin/python > requirements-dataset.txt
    .venv-dataset/bin/openarm-dataset-convert --help >/dev/null
    echo 'Dataset conversion environment installed in .venv-dataset.'
    exit 0
fi
if [[ ! -x .venv/bin/python ]]; then uv venv --python 3.12 .venv; fi
if [[ "$mode" == core ]]; then
    uv pip install --python .venv/bin/python -c constraints.txt \
        dora-rs-cli -e openarm_mujoco -e openarm_control \
        -e dora-openarm-data-collection/nodes/dora-openarm-stereo-camera \
        -e dora-openarm-data-collection/nodes/dora-openarm-webxr \
        -e dora-openarm-data-collection/nodes/dora-openarm-kinematics \
        -e dora-openarm-data-collection/nodes/dora-openarm-data-collection-ui \
        -e dora-openarm-data-collection/nodes/dora-openarm-quitter \
        -e dora-openarm-data-collection/nodes/dora-openarm-dataset-recorder
else
    uv pip install --python .venv/bin/python -c constraints.txt \
        -e dora-openarm-data-collection/nodes/dora-openarm
    .venv/bin/python -c 'import openarm_driver, openarm_can; print("Hardware imports OK; no motor connection attempted")'
fi
uv pip check --python .venv/bin/python
uv pip freeze --python .venv/bin/python > "requirements-jetson-${mode}.txt"
echo 'Installed. No CAN configuration or motor startup was performed.'
