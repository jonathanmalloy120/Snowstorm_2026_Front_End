#!/usr/bin/env bash
# Run the snapshot poller so macOS does not suspend it.
#
# Coverage without this was ~11%: the process never crashed, it just stopped
# being scheduled. App Nap throttles background processes, and idle/system
# sleep stops them entirely. Signals does not backdate, so every minute the
# poller is not scheduled is history that cannot be recovered.
#
#   caffeinate -i  prevent IDLE sleep
#   caffeinate -s  prevent SYSTEM sleep -- ONLY effective on AC power
#
# WHAT THIS DOES NOT FIX: a sleeping Mac runs nothing. Unplug the laptop or
# close the lid and polling stops until it wakes, leaving an unrecoverable gap.
# This covers App Nap and idle sleep while plugged in -- nothing more.
#
# A launchd agent does not help either: it restarts the poller after wake and
# reboot, but still cannot run during sleep. It is also blocked outright here,
# because macOS TCC denies LaunchAgents read access to ~/Documents, where this
# repo lives (verified: a test agent runs fine but cannot `ls` the project).
#
# The only gap-free option is to run the poller and Postgres off the laptop.
#
# Usage (detached, survives closing the terminal):
#   nohup ./run_poller.sh >> poller.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")"
exec caffeinate -is uv run python -m poller.run
