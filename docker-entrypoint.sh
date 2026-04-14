#!/bin/sh
set -e
WORKDIR_PATH="${WORK_DIR:-/tmp/ffmpeg-gateway-work}"
mkdir -p "$WORKDIR_PATH/uploads" "$WORKDIR_PATH/outputs" "$WORKDIR_PATH/scripts"
chown -R appuser:appuser "$WORKDIR_PATH"
exec runuser -u appuser -- "$@"
