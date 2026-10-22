#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
# Drive tests/qa/linux_bubble_wm_chrome.py under Xvfb plus one or more WMs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${MIXAR_QA_OUT:-/tmp/mixar-bubble-wm-chrome}"
if [ "$#" -eq 0 ]; then
  set -- xfwm4 openbox
fi
mkdir -p "$OUT"

pick_display() {
  local n
  for n in $(seq 110 149); do
    if [ ! -e "/tmp/.X11-unix/X$n" ] && [ ! -e "/tmp/.X$n-lock" ]; then
      echo ":$n"
      return 0
    fi
  done
  return 1
}

run_wm() {
  local wm="$1"
  local display="${2:?}"
  case "$wm" in
    xfwm4) DISPLAY="$display" xfwm4 --compositor=off --replace >/dev/null 2>&1 & ;;
    openbox) DISPLAY="$display" openbox >/dev/null 2>&1 & ;;
    metacity) DISPLAY="$display" dbus-run-session -- metacity --replace --sm-disable >/dev/null 2>&1 & ;;
    *) echo "unknown WM: $wm" >&2; return 2 ;;
  esac
  local wm_pid=$!
  for _ in $(seq 1 25); do
    if kill -0 "$wm_pid" 2>/dev/null && \
       xprop -root _NET_SUPPORTING_WM_CHECK >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "$wm failed to advertise _NET_SUPPORTING_WM_CHECK" >&2
  return 1
}

status=0
for wm in "$@"; do
  if ! command -v "$wm" >/dev/null 2>&1; then
    echo "skip $wm (not installed)"
    continue
  fi
  display="$(pick_display)" || { echo "no free X display"; status=1; continue; }
  log="$OUT/${wm}.log"
  echo "=== $wm on $display ==="
  Xvfb "$display" -screen 0 1280x800x24 >/dev/null 2>&1 &
  xvfb_pid=$!
  export DISPLAY="$display"
  export MIXAR_QA_WM="$wm"
  xvfb_ready=0
  for _ in $(seq 1 25); do
    if kill -0 "$xvfb_pid" 2>/dev/null && [ -e "/tmp/.X11-unix/X${display#:}" ]; then
      xvfb_ready=1
      break
    fi
    sleep 0.1
  done
  if [ "$xvfb_ready" -ne 1 ]; then
    echo "Xvfb failed to start on $display" >&2
    kill "$xvfb_pid" 2>/dev/null || true
    status=1
    continue
  fi
  if ! run_wm "$wm" "$display"; then
    kill "$xvfb_pid" 2>/dev/null || true
    status=1
    continue
  fi
  if python3 "$ROOT/tests/qa/linux_bubble_wm_chrome.py" | tee "$log"; then
    echo "$wm: PASS"
  else
    echo "$wm: FAIL"
    status=1
  fi
  kill "$xvfb_pid" 2>/dev/null || true
  wait "$xvfb_pid" 2>/dev/null || true
done
exit "$status"
