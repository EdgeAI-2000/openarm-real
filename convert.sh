#!/usr/bin/env bash
set -euo pipefail

root_dir="$(dirname "$(realpath "$0")")"
cd "$root_dir"

usage() {
    cat >&2 <<'EOF'
Usage: bash convert.sh INPUT_DATASET [OUTPUT_DATASET]

Environment overrides:
  LEROBOT_FORMAT              lerobot_v3.0 (default) or lerobot_v2.1
  LEROBOT_FPS                 30 (default)
  LEROBOT_SMOOTHING_CUTOFF    1.0 (default; Hz)
  LEROBOT_TRAIN_SPLIT         0.8 (default)
  LEROBOT_STATE               qpos (default), pose, or rot6d
  LEROBOT_INCLUDE_FAILURES    0 (default); set to 1 to include failed episodes
  LEROBOT_INCLUDE_INVALID     0 (default); set to 1 to include invalid episodes
  OPENARM_QPOS_JUMP_THRESHOLD 1.0 (default; use none to disable)
  OPENARM_QPOS_ABSMAX         6.28 (default; use none to disable)
  OPENARM_MIN_DURATION        2.0 (default; use none to disable)
EOF
    exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
input_dir="$(realpath -e "$1")"
[[ -d "$input_dir" && -f "$input_dir/metadata.yaml" ]] || {
    echo "Not an OpenArm dataset root (metadata.yaml is missing): $input_dir" >&2
    exit 1
}

format="${LEROBOT_FORMAT:-lerobot_v3.0}"
case "$format" in lerobot_v3.0|lerobot_v2.1) ;; *) echo "Unsupported LEROBOT_FORMAT: $format" >&2; exit 2;; esac
fps="${LEROBOT_FPS:-30}"
smoothing_cutoff="${LEROBOT_SMOOTHING_CUTOFF:-1.0}"
train_split="${LEROBOT_TRAIN_SPLIT:-0.8}"
state="${LEROBOT_STATE:-qpos}"
case "$state" in qpos|pose|rot6d) ;; *) echo "Unsupported LEROBOT_STATE: $state" >&2; exit 2;; esac
include_failures="${LEROBOT_INCLUDE_FAILURES:-0}"
include_invalid="${LEROBOT_INCLUDE_INVALID:-0}"
case "$include_failures" in 0|1) ;; *) echo 'LEROBOT_INCLUDE_FAILURES must be 0 or 1.' >&2; exit 2;; esac
case "$include_invalid" in 0|1) ;; *) echo 'LEROBOT_INCLUDE_INVALID must be 0 or 1.' >&2; exit 2;; esac

if [[ $# -eq 2 ]]; then
    output_dir="$(realpath -m "$2")"
else
    output_dir="$root_dir/lerobot_data/$(basename "$input_dir")-${format//./_}"
fi
[[ "$input_dir" != "$output_dir" ]] || { echo 'Input and output paths must differ.' >&2; exit 1; }
[[ ! -e "$output_dir" ]] || {
    echo "Output already exists; choose a new directory so a prior conversion is not overwritten: $output_dir" >&2
    exit 1
}

python_bin="$root_dir/.venv-dataset/bin/python"
validator="$root_dir/.venv-dataset/bin/openarm-dataset-validate"
converter="$root_dir/.venv-dataset/bin/openarm-dataset-convert"
[[ -x "$python_bin" && -x "$validator" && -x "$converter" ]] || {
    echo 'Dataset tools are not installed. Run: bash install.sh dataset' >&2
    exit 1
}
command -v ffmpeg >/dev/null || { echo 'ffmpeg is required for camera video encoding.' >&2; exit 1; }

preflight_args=("$input_dir" --state "$state")
convert_args=(
    "$input_dir" "$output_dir"
    --format "$format"
    --fps "$fps"
    --smoothing-cutoff "$smoothing_cutoff"
    --train-split "$train_split"
    --state "$state"
)
if [[ "$include_failures" == 0 ]]; then
    preflight_args+=(--success-only)
    convert_args+=(--success-only)
fi
if [[ "$include_invalid" == 0 ]]; then
    preflight_args+=(--valid-only)
    convert_args+=(--valid-only)
fi

# Catch missing metadata/modalities with a concise message before invoking the
# official validator, whose CLI otherwise prints a Python traceback for these.
"$python_bin" scripts/check_openarm_dataset.py "${preflight_args[@]}"
echo "Validating OpenArm dataset: $input_dir"
validation_status=0
"$validator" "$input_dir" \
    --qpos-jump-threshold "${OPENARM_QPOS_JUMP_THRESHOLD:-1.0}" \
    --qpos-absmax "${OPENARM_QPOS_ABSMAX:-6.28}" \
    --min-duration "${OPENARM_MIN_DURATION:-2.0}" || validation_status=$?
if (( validation_status != 0 )); then
    if [[ "$include_invalid" == 1 ]]; then
        echo 'Validation failed and LEROBOT_INCLUDE_INVALID=1; refusing to export known-invalid episodes.' >&2
        exit "$validation_status"
    fi
    echo 'Validation found invalid episodes; they will be excluded.' >&2
fi
# Validation may have newly marked episodes invalid, so check the filtered set
# once more and fail clearly if nothing usable remains.
"$python_bin" scripts/check_openarm_dataset.py "${preflight_args[@]}"
echo "Converting to $format: $output_dir"
"$converter" "${convert_args[@]}"
"$python_bin" scripts/verify_lerobot_dataset.py "$output_dir" --format "$format"
echo "Conversion complete: $output_dir"
