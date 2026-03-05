#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <plan_path> <expected_dev_count>" >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage
  exit 2
fi

plan_path="$1"
expected_dev_count="$2"

if [[ ! -f "$plan_path" ]]; then
  echo "ERROR: plan file not found: $plan_path" >&2
  exit 2
fi

if ! [[ "$expected_dev_count" =~ ^[0-9]+$ ]] || (( expected_dev_count < 1 )); then
  echo "ERROR: expected_dev_count must be a positive integer, got: $expected_dev_count" >&2
  exit 2
fi

missing_ack=0
for dev_num in $(seq 1 "$expected_dev_count"); do
  heading="#### Dev-${dev_num} Notes:"

  if ! grep -Fq "$heading" "$plan_path"; then
    echo "ERROR: missing section heading '$heading' in $plan_path" >&2
    missing_ack=1
    continue
  fi

  section_content="$(
    awk -v heading="$heading" '
      $0 == heading { in_section=1; next }
      in_section && $0 ~ /^#### / { exit }
      in_section { print }
    ' "$plan_path"
  )"

  if ! grep -Fq "[ACK]" <<<"$section_content"; then
    echo "ERROR: Dev-${dev_num} is missing [ACK] in '$heading'" >&2
    missing_ack=1
  fi
done

if (( missing_ack )); then
  echo "ACK gate failed. Do not launch execution prompts." >&2
  exit 1
fi

echo "ACK gate passed for Dev-1..Dev-${expected_dev_count} in $plan_path"
