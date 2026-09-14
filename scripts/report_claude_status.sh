#!/usr/bin/env bash
# Reports this Claude Code session's status into the external-agent status feed
# (see services/api/routes/external_agents.py) so it shows up as a live avatar on
# the /world admin-web page. Intended to be called from a Claude Code hook (see
# .claude/settings.local.json.example) on UserPromptSubmit ("working") and Stop
# ("done") — but safe to call by hand too.
#
# Reads its target/credentials from env vars rather than taking them as literal
# arguments, so nothing here needs a secret hardcoded into a tracked file:
#   DAYTHREE_API_BASE_URL     default http://localhost:8000
#   DAYTHREE_AGENT_NAME       default claude-code
#   DAYTHREE_ADMIN_EMAIL      default admin@daythree.local
#   DAYTHREE_ADMIN_PASSWORD   required — if unset, this silently no-ops
#
# Always exits 0: a hook that can block Claude Code (exit code 2) or that fails
# loudly when the local stack isn't running would be worse than a missed status
# update, so every failure path here is a silent no-op.
set -u

STATUS="${1:-idle}"
DESCRIPTION="${2:-}"

BASE_URL="${DAYTHREE_API_BASE_URL:-http://localhost:8000}"
AGENT_NAME="${DAYTHREE_AGENT_NAME:-claude-code}"
EMAIL="${DAYTHREE_ADMIN_EMAIL:-admin@daythree.local}"
PASSWORD="${DAYTHREE_ADMIN_PASSWORD:-}"

[ -z "$PASSWORD" ] && exit 0

TOKEN=$(curl -s --max-time 3 --connect-timeout 2 -X POST "$BASE_URL/api/v1/auth/login" \
  --data-urlencode "username=$EMAIL" --data-urlencode "password=$PASSWORD" 2>/dev/null |
  sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')

[ -z "$TOKEN" ] && exit 0

ESCAPED_DESCRIPTION=$(printf '%s' "$DESCRIPTION" | sed 's/\\/\\\\/g; s/"/\\"/g')

curl -s --max-time 3 --connect-timeout 2 -X PUT \
  "$BASE_URL/api/v1/external-agents/$AGENT_NAME/status" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"status\":\"$STATUS\",\"job_description\":\"$ESCAPED_DESCRIPTION\"}" \
  >/dev/null 2>&1

exit 0
