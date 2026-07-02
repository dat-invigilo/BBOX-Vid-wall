#!/bin/bash
set -e

# Runs mediamtx (RTSP->HLS relay) and the Flask web server as sibling
# processes in the same container, since they always deploy together on
# the same host network (see mediamtx-migration.md). If either exits, the
# container exits so the orchestrator (docker/IoT Edge) can restart it.

cleanup() {
    echo "Shutting down..."
    kill -TERM "$MEDIAMTX_PID" "$WEBSERVER_PID" 2>/dev/null || true
    wait "$MEDIAMTX_PID" "$WEBSERVER_PID" 2>/dev/null || true
}
trap cleanup TERM INT

mediamtx /app/mediamtx.yml &
MEDIAMTX_PID=$!

python web_server.py &
WEBSERVER_PID=$!

wait -n "$MEDIAMTX_PID" "$WEBSERVER_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
