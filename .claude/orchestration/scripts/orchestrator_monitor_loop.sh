#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <project_root> <num_devs> [poll_seconds] [stall_seconds]" >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 || $# -gt 4 ]]; then
  usage
  exit 2
fi

project_root="${1%/}"
num_devs="$2"
poll_seconds="${3:-30}"
stall_seconds="${4:-300}"

if [[ ! -d "$project_root" ]]; then
  echo "ERROR: project_root does not exist: $project_root" >&2
  exit 2
fi
if ! [[ "$num_devs" =~ ^[0-9]+$ ]] || (( num_devs < 1 )); then
  echo "ERROR: num_devs must be a positive integer, got: $num_devs" >&2
  exit 2
fi
if ! [[ "$poll_seconds" =~ ^[0-9]+$ ]] || (( poll_seconds < 1 )); then
  echo "ERROR: poll_seconds must be a positive integer, got: $poll_seconds" >&2
  exit 2
fi
if ! [[ "$stall_seconds" =~ ^[0-9]+$ ]] || (( stall_seconds < poll_seconds )); then
  echo "ERROR: stall_seconds must be >= poll_seconds, got: $stall_seconds" >&2
  exit 2
fi

run_dir="$project_root/orchestration_run"
log_dir="$run_dir/logs"
plan_path="$run_dir/plan.md"
findings_path="$run_dir/findings.md"
stop_file="$run_dir/.stop_monitor_loop"
heartbeat_log="$log_dir/orchestrator_heartbeat.log"

mkdir -p "$log_dir"
touch "$heartbeat_log"

epoch_now() {
  date +%s
}

file_mtime_epoch() {
  local p="$1"
  stat -f %m "$p" 2>/dev/null || stat -c %Y "$p" 2>/dev/null
}

count_pattern() {
  local pattern="$1"
  local file="$2"
  if [[ -f "$file" ]]; then
    grep -c "$pattern" "$file" 2>/dev/null || true
  else
    echo 0
  fi
}

count_total_jsonl_lines() {
  local total=0
  shopt -s nullglob
  local f
  for f in "$log_dir"/*.jsonl; do
    local lines=0
    lines=$(wc -l < "$f" 2>/dev/null || echo 0)
    total=$((total + lines))
  done
  shopt -u nullglob
  echo "$total"
}

latest_file_age() {
  local glob="$1"
  local now_epoch="$2"
  shopt -s nullglob
  local files=($glob)
  shopt -u nullglob
  if (( ${#files[@]} == 0 )); then
    echo -1
    return 0
  fi
  local newest="${files[0]}"
  local newest_mtime=0
  local f mtime
  for f in "${files[@]}"; do
    mtime=$(file_mtime_epoch "$f" || echo 0)
    if (( mtime > newest_mtime )); then
      newest_mtime="$mtime"
      newest="$f"
    fi
  done
  if (( newest_mtime == 0 )); then
    echo -1
    return 0
  fi
  echo $((now_epoch - newest_mtime))
}

log_line() {
  local ts="$1"
  local level="$2"
  local msg="$3"
  printf '[%s] [ORCH-MONITOR] [%s] — %s\n' "$ts" "$level" "$msg" >> "$heartbeat_log"
}

prev_total_lines=0
last_growth_epoch="$(epoch_now)"

ts="$(date '+%Y-%m-%d %H:%M:%S')"
log_line "$ts" "START" "monitor loop started (num_devs=$num_devs poll=${poll_seconds}s stall=${stall_seconds}s)"

while true; do
  if [[ -f "$stop_file" ]]; then
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    log_line "$ts" "STOP" "stop file detected: $stop_file"
    exit 0
  fi

  now_epoch="$(epoch_now)"
  ts="$(date '+%Y-%m-%d %H:%M:%S')"

  ack_count="$(count_pattern "\\[ACK\\]" "$plan_path")"
  done_count="$(count_pattern "\\[DONE\\]" "$plan_path")"
  fix_count="$(count_pattern "\\[FIX\\]" "$plan_path")"
  crosstest_fail_count="$(count_pattern "\\[CROSS_TEST_FAIL\\]" "$plan_path")"
  crosstest_blocked_count="$(count_pattern "\\[CROSS_TEST_BLOCKED\\]" "$plan_path")"

  reviewer_age="$(latest_file_age "$log_dir/reviewer_stream.jsonl" "$now_epoch")"
  watcher_age="$(latest_file_age "$log_dir/live_watch_*.jsonl" "$now_epoch")"
  scribe_age="$(latest_file_age "$log_dir/scribe_*.jsonl" "$now_epoch")"
  findings_age="$(latest_file_age "$findings_path" "$now_epoch")"

  total_lines="$(count_total_jsonl_lines)"
  if (( total_lines > prev_total_lines )); then
    last_growth_epoch="$now_epoch"
  fi
  prev_total_lines="$total_lines"
  stall_age=$((now_epoch - last_growth_epoch))

  alerts=()
  if (( done_count > 0 && reviewer_age < 0 )); then
    alerts+=("reviewer_missing_after_done")
  fi
  if (( done_count > 0 && watcher_age < 0 )); then
    alerts+=("watcher_missing_after_done")
  fi
  if (( watcher_age >= 0 && watcher_age > 900 )); then
    alerts+=("watcher_snapshot_stale")
  fi
  if (( stall_age > stall_seconds )); then
    alerts+=("stream_stalled")
  fi
  if (( crosstest_blocked_count > 0 )); then
    alerts+=("cross_test_blocked_present")
  fi

  if (( ${#alerts[@]} == 0 )); then
    log_line "$ts" "HEARTBEAT" \
      "ack=$ack_count done=$done_count fix=$fix_count ctfail=$crosstest_fail_count ctblocked=$crosstest_blocked_count lines=$total_lines stall_age=${stall_age}s reviewer_age=${reviewer_age}s watcher_age=${watcher_age}s scribe_age=${scribe_age}s findings_age=${findings_age}s"
  else
    log_line "$ts" "ALERT" \
      "alerts=$(IFS=,; echo "${alerts[*]}") ack=$ack_count done=$done_count lines=$total_lines stall_age=${stall_age}s reviewer_age=${reviewer_age}s watcher_age=${watcher_age}s"
  fi

  sleep "$poll_seconds"
done
