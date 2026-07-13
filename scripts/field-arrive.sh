#!/usr/bin/env bash
set -euo pipefail

# Local, file-based arrival ritual for TERMITE_PROTOCOL.md v5.1.
# It intentionally uses the protocol's graceful-degradation path: versioned
# Markdown/YAML for shared state, ignored per-session files for runtime state.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f TERMITE_PROTOCOL.md || ! -f BLACKBOARD.md ]]; then
  echo "Termite Protocol is not initialized: TERMITE_PROTOCOL.md and BLACKBOARD.md are required." >&2
  exit 1
fi

agent_id="termite-$(date +%s)-$$"
directive="${*:-}"
branch="$(git branch --show-current 2>/dev/null || printf 'no-git')"
git_status="$(git status --short 2>/dev/null || true)"
if [[ -z "$git_status" ]]; then
  git_state="clean"
else
  git_change_count="$(printf '%s\n' "$git_status" | awk 'END { print NR }')"
  git_state="$(printf '%s\n' "$git_status" | sed -n '1,20p')"
  if (( git_change_count > 20 )); then
    git_state+=$'\n'"... plus $((git_change_count - 20)) more changed paths"
  fi
fi

best_signal=""
best_weight=-1
for signal in signals/active/*.yaml; do
  [[ -f "$signal" ]] || continue
  status="$(awk -F': *' '$1 == "status" { print $2; exit }' "$signal")"
  [[ "$status" == "done" || "$status" == "archived" ]] && continue
  weight="$(awk -F': *' '$1 == "weight" { print $2; exit }' "$signal")"
  [[ "$weight" =~ ^[0-9]+$ ]] || weight=0
  if (( weight > best_weight )); then
    best_weight=$weight
    best_signal="$signal"
  fi
done

signal_summary="none"
if [[ -n "$best_signal" ]]; then
  signal_id="$(awk -F': *' '$1 == "id" { print $2; exit }' "$best_signal")"
  signal_title="$(awk -F': *' '$1 == "title" { sub(/^[^:]*: */, ""); gsub(/^\"|\"$/, ""); print; exit }' "$best_signal")"
  signal_next="$(awk -F': *' '$1 == "next" { sub(/^[^:]*: */, ""); gsub(/^\"|\"$/, ""); print; exit }' "$best_signal")"
  signal_summary="$signal_id (weight $best_weight): $signal_title"$'\n'"Next: $signal_next"
fi

caste="scout"
reason="no directive, alarm, fresh WIP, or high-priority signal"
if [[ -f ALARM.md ]]; then
  caste="soldier"
  reason="ALARM.md exists; read it and restore health first"
elif [[ -n "$directive" ]]; then
  caste="scout-then-worker"
  reason="human directive supplied; scope and plan before implementation"
elif [[ -f WIP.md ]] && find WIP.md -mtime -14 -print -quit | grep -q .; then
  caste="worker"
  reason="fresh WIP.md exists; continue the recorded handoff"
elif (( best_weight >= 50 )); then
  caste="worker"
  reason="a high-weight active signal needs action"
fi

birth_file=".birth.$agent_id"
cat > "$birth_file" <<EOF
# termite-birth:v5.1
agent_id: $agent_id
branch: $branch
caste: $caste
reason: $reason

## grammar
ARRIVE → SENSE → STATE → CASTE → PERMISSIONS → DO → DEPOSIT.
Work only within the selected role. Human instructions win. Read ALARM.md before work if it exists.

## safety
S1: explain what and why in commits. S2: do not silently delete Markdown control files.
S3: at more than 50 changed lines, make a [WIP] commit when appropriate. S4: ALARM first.

## situation
Git: $git_state
Blackboard: BLACKBOARD.md
Directive: ${directive:-none}
Active signal: $signal_summary

## next
1. Read BLACKBOARD.md and the selected signal/WIP/ALARM file.
2. Confirm the role boundary above, then follow AGENTS.md for the video workflow.
3. Before handing off, update a signal, BLACKBOARD.md, DECISIONS.md, or WIP.md with verified facts.
EOF

cp "$birth_file" .birth
printf 'agent_id: %s\nbranch: %s\ncaste: %s\nupdated: %s\n' \
  "$agent_id" "$branch" "$caste" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .field-breath

printf 'Termite arrival complete: %s (%s). Read %s and .birth.\n' "$agent_id" "$caste" "$birth_file"
