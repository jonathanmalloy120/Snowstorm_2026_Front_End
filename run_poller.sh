#!/usr/bin/env bash
# Run the snapshot poller so macOS does not suspend it.
#
# Coverage without this was ~11%: the process never crashed, it just stopped
# being scheduled. App Nap throttles background processes, and idle/system
# sleep stops them entirely. Signals does not backdate, so every minute the
# poller is not scheduled is history that cannot be recovered.
#
#   caffeinate -i  prevent IDLE sleep
#   caffeinate -s  prevent SYSTEM sleep -- NOTE: only effective on AC power
#
# Usage (detached, survives closing the terminal):
#   nohup ./run_poller.sh >> poller.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")"
exec caffeinate -is uv run python -m poller.run
