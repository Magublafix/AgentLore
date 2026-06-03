#!/usr/bin/env bash
# Lore Stop hook — fires when a Claude Code session ends.
# Reads ~/.lore/session.json, prompts Claude to rate used concepts,
# injects a session-end reflection prompt, then clears the session file.
# Always exits 0 — never blocks session close.

SESSION_FILE="${HOME}/.lore/session.json"
SELFHOSTED_URL="${LORE_SELFHOSTED_URL:-http://localhost:8765}"

log() { printf '[lore-stop] %s\n' "$*" >&2; }

read_session() {
  if [[ ! -f "${SESSION_FILE}" ]]; then
    echo "[]"
    return
  fi
  local content
  content=$(cat "${SESSION_FILE}" 2>/dev/null || echo "[]")
  if ! echo "${content}" | python3 -c "import sys,json; d=json.load(sys.stdin); assert isinstance(d,list)" 2>/dev/null; then
    log "Session file is not a valid JSON array — treating as empty."
    echo "[]"
    return
  fi
  echo "${content}"
}

clear_session() {
  mkdir -p "$(dirname "${SESSION_FILE}")"
  echo "[]" > "${SESSION_FILE}"
}

lookup_concept_name() {
  local id="$1"
  # Returns "name (type)" or just the ID if the backend is unreachable
  local result
  result=$(curl -sf --max-time 2 "${SELFHOSTED_URL}/v1/concepts/${id}" 2>/dev/null) || { echo "${id}"; return; }
  python3 -c "
import sys, json
try:
    d = json.loads('''${result}''')
    print(d.get('name', '${id}') + ' (' + d.get('type', '?') + ')')
except Exception:
    print('${id}')
" 2>/dev/null || echo "${id}"
}

main() {
  local session_json
  session_json=$(read_session)

  local concept_ids
  mapfile -t concept_ids < <(python3 -c "
import sys, json
ids = json.loads('''${session_json}''')
for i in ids:
    if isinstance(i, str) and i.strip():
        print(i.strip())
" 2>/dev/null)

  if [[ ${#concept_ids[@]} -eq 0 ]]; then
    log "No concepts in session — nothing to rate."
    exit 0
  fi

  log "Session contained ${#concept_ids[@]} concept(s)."

  # Resolve concept names (best-effort — falls back to ID if backend is down)
  local concept_labels=()
  for id in "${concept_ids[@]}"; do
    concept_labels+=("$(lookup_concept_name "${id}")")
  done

  # Emit rating prompt — stdout is read by Claude Code as a post-session instruction
  echo ""
  echo "---"
  echo "[Lore — session-end review]"
  echo ""
  echo "You used ${#concept_ids[@]} Lore concept(s) this session:"
  echo ""
  for i in "${!concept_ids[@]}"; do
    echo "  $((i+1)). ${concept_labels[$i]}"
    echo "     id: ${concept_ids[$i]}"
  done
  echo ""
  echo "For each concept, call rate_concept with:"
  echo "  - concept_id: the ID listed above"
  echo "  - outcome: 1–5 (how useful was this concept?)"
  echo "  - hours_saved: your honest estimate of hours saved (omit if zero or uncertain)"
  echo "  - session_id: use the current session identifier"
  echo ""
  echo "Rate all concepts now."
  echo ""
  echo "---"
  echo "[Lore — session-end reflection]"
  echo ""
  echo "Reflect on this session: did you encounter any non-trivial patterns, gotchas,"
  echo "or solutions that would save another agent meaningful time?"
  echo "If yes, call /capture-concept for each one before closing."
  echo "---"
  echo ""

  clear_session
  log "Session cleared."
}

main "$@"
exit 0
