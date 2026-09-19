#!/usr/bin/env bash
# Claude Code hook -> daythree-ai-world digital-twin lifecycle (build plan phase T3).
#
# One script for six hook events: SessionStart, SubagentStart, SubagentStop, SessionEnd,
# Stop, UserPromptSubmit. It registers the session and its roster subagents, closes them,
# and heartbeats the session so the reaper never mistakes a live session for a lost one.
# It never blocks or slows Claude Code: it always exits 0, prints nothing on stdout or
# stderr (SessionStart and UserPromptSubmit stdout is injected into the model context),
# and every network call is bounded to about 2 seconds.
#
# Payload contract (Claude Code 2.1.227; official hooks documentation plus the
# key-names-only capture recorded in docs/council/LEDGER.md). The ONLY fields ever read:
#   SessionStart          session_id, hook_event_name, source (startup resume clear compact fork)
#   SessionEnd            session_id, reason (clear resume logout prompt_input_exit other)
#   Stop, UserPromptSubmit  session_id, hook_event_name
#   SubagentStart/Stop    session_id, agent_id, agent_type
# Never read, logged, hashed or forwarded: prompt, cwd, transcript_path,
# agent_transcript_path, tool_input, tool_result, last_assistant_message, session_title,
# background_tasks, session_crons, scratchpad_dir, permission_mode, and every other field.
# No payload carries a tool-call count, so none is ever sent. Outcome and reason on a
# subagent close are declared by this hook, not measured.
#
# Parsing: one awk pass tokenises the payload and keeps only TOP-LEVEL string members whose key
# is on a short allow-list and whose value is a short class-restricted token (a nested object or
# array, or a key inside a string, can never match). Every value is then re-validated in bash,
# and the request body is assembled from validated tokens only. No jq, no python.
#
# Configuration (never from the payload):
#   $HOME/.daythree/twin_env.sh   two lines, DAYTHREE_TWIN_BASE_URL=<url> and DAYTHREE_TWIN_KEY=<key>
#                                 (see .claude/twin_env.sh.example). The file is READ, never
#                                 executed: only those two lines are accepted, each value is
#                                 validated, and comments, blanks, `export` lines and anything
#                                 else are ignored. There are no defaults: with either missing
#                                 the hook exits 0 and logs one `no_key` line.
#   TWIN_HOME       TEST-ONLY override: use $TWIN_HOME instead of $HOME for the key file, and
#                   $TWIN_HOME/.hook-debug instead of <repo>/.hook-debug for state and log.
#                   Never set it in the hook command or the settings file.
#   TWIN_DRY_RUN=1  TEST-ONLY: make no network call and read no key; append each request this
#                   script would send ("METHOD path body" per line) to the file named by
#                   TWIN_DRY_RUN_FILE (honoured only when TWIN_DRY_RUN=1).
#
# State and log (gitignored, ids and enums only, never a secret):
#   .hook-debug/twin-state/<claude-session-id>   "run-uuid runtime-uuid|- last-heartbeat-epoch"
#   .hook-debug/twin_lifecycle.log               "UTC event class http-code pid [8-char ref]"
#   .hook-debug/twin-failures/<event>            one epoch line per failure, counted at Gate E
#
# Known limits: the log and the failure files are trimmed by rewriting them past 256 KiB; a line
# appended by a parallel hook during that rewrite can be lost (the state file, which matters, is
# written atomically and is not trimmed). A SubagentStart racing a SessionEnd for the same run in
# the same millisecond can register a Task under an ended run; the reaper heals that.

exec >/dev/null 2>&1
trap 'exit 0' EXIT
set +x
# A variable this script assigns keeps its export attribute if the caller's environment already
# holds one of the same name, and would then reach curl's environment with the script's value
# (the curl config with the key, the payload). Unset EVERY identifier the script assigns, before
# anything is assigned; tests/hooks derive this list from the script text.
unset -v BASH_XTRACEFD DAYTHREE_TWIN_BASE_URL DAYTHREE_TWIN_KEY \
  ROSTER MAX_PAYLOAD HEARTBEAT_SECONDS LOG_CAP UUID_RE REF_RE KEY_RE URL_RE \
  AWK_TOP HOME_DIR STATE_ROOT SCRIPT_PATH SCRIPT_DIR STATE_DIR FAIL_DIR LOG_FILE \
  KEY_FILE EVENT EVENT_RAW SESSION_ID LOG_REF CLEANUP_STATE CONFIG_OK TW_BASE_URL \
  TW_KEY LOOPBACK CURL_OPTS HTTP_CODE RESP NOW UUID CLASS \
  S_OK S_RUN S_RT S_HB REG_RT FMT payload FLAT \
  PAIRS e days secs z era doe yoe \
  y doy mp d m file content ref \
  f n hex i variants a b c \
  tmp host line url key method path body \
  attempt out rc code esc cfg source run \
  type frag refused new_run elapsed reason outcome t \
  v budget
LC_ALL=C
umask 077

readonly ROSTER=" planner architect code-reviewer tdd-guide security-reviewer "
readonly MAX_PAYLOAD=1048576
readonly HEARTBEAT_SECONDS=300
readonly LOG_CAP=262144
readonly UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
readonly REF_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
readonly KEY_RE='^dtk_[0-9a-f]{32}_[A-Za-z0-9_-]{20,128}$'
readonly URL_RE='^(https?)://([A-Za-z0-9.-]+|\[::1\])(:[0-9]{1,5})?$'

if [ -n "${TWIN_HOME:-}" ]; then
  HOME_DIR=$TWIN_HOME
  STATE_ROOT="$TWIN_HOME/.hook-debug"
else
  HOME_DIR=${HOME:-}
  SCRIPT_PATH=${BASH_SOURCE[0]//\\//}
  if [[ $SCRIPT_PATH == */* ]]; then SCRIPT_DIR=${SCRIPT_PATH%/*}; else SCRIPT_DIR=.; fi
  STATE_ROOT="$SCRIPT_DIR/../.hook-debug"
fi
STATE_DIR="$STATE_ROOT/twin-state"
FAIL_DIR="$STATE_ROOT/twin-failures"
LOG_FILE="$STATE_ROOT/twin_lifecycle.log"
KEY_FILE="$HOME_DIR/.daythree/twin_env.sh"

EVENT=
SESSION_ID=
LOG_REF=
CLEANUP_STATE=
CONFIG_OK=
TW_BASE_URL=
TW_KEY=
LOOPBACK=
CURL_OPTS=()
HTTP_CODE=000
RESP=
NOW=0
UUID=
CLASS=
S_OK=0 S_RUN= S_RT= S_HB=0
REG_RT=

# ---------------------------------------------------------------- time, log, exit

now_epoch() { printf -v NOW '%(%s)T' -1; }

# UTC without any dependence on TZ handling: epoch -> YYYY-MM-DDTHH:MM:SSZ.
fmt_utc() {
  local e=$1 days secs z era doe yoe y doy mp d m
  days=$((e / 86400)) secs=$((e % 86400))
  z=$((days + 719468)) era=$((z / 146097)) doe=$((z - era * 146097))
  yoe=$(((doe - doe / 1460 + doe / 36524 - doe / 146096) / 365))
  y=$((yoe + era * 400)) doy=$((doe - (365 * yoe + yoe / 4 - yoe / 100)))
  mp=$(((5 * doy + 2) / 153)) d=$((doy - (153 * mp + 2) / 5 + 1))
  if [ "$mp" -lt 10 ]; then m=$((mp + 3)); else m=$((mp - 9)); fi
  if [ "$m" -le 2 ]; then y=$((y + 1)); fi
  printf -v FMT '%04d-%02d-%02dT%02d:%02d:%02dZ' "$y" "$m" "$d" $((secs / 3600)) $((secs % 3600 / 60)) $((secs % 60))
}

# append_capped FILE LINE: append one line; past 256 KiB keep only the newest half first.
append_capped() {
  local file=$1 content
  mkdir -p "${file%/*}" || return 0
  if [ -f "$file" ]; then
    content=$(<"$file")
    if [ "${#content}" -gt "$LOG_CAP" ]; then
      content=${content: -131072}
      content=${content#*$'\n'}
      if printf '%s\n' "$content" >"$file.tmp.$$"; then mv -f "$file.tmp.$$" "$file" || rm -f "$file.tmp.$$"; else rm -f "$file.tmp.$$"; fi
    fi
  fi
  printf '%s\n' "$2" >>"$file"
}

log_line() { # class code ref
  local ref=${3:-}
  now_epoch
  fmt_utc "$NOW"
  ref=${ref:0:8}
  append_capped "$LOG_FILE" "$FMT ${EVENT:--} $1 ${2:--} $$ ${ref:--}"
}

# One epoch line per failure, appended (no read-modify-write, so parallel hooks cannot lose
# a count); Gate E counts the lines, optionally inside a time window.
bump_failure() {
  append_capped "$FAIL_DIR/${EVENT:-unknown}" "$NOW"
}

# finish CLASS [HTTP-CODE] [REF]: the only exit. One log line, a failure count for every
# class that means "this event did not reach the platform", then exit 0.
finish() {
  local ref=${3:-$LOG_REF}
  if [ -n "$CLEANUP_STATE" ] && [ -n "$SESSION_ID" ]; then rm -f "$STATE_DIR/$SESSION_ID"; fi
  log_line "$1" "${2:--}" "$ref"
  case $1 in
    ok | throttled | ignored | duplicate | reused | reregistered) ;;
    *) bump_failure ;;
  esac
  exit 0
}

# ---------------------------------------------------------------- parsing

# Top-level string members only. RS is the double quote, so records alternate between text
# outside a string and the content of a string; a string whose closing quote is escaped
# (an odd run of backslashes) is joined with the next record. Bracket depth is counted in the
# outside-string text only, so braces inside strings never matter. A member is emitted as
# `key=value` when it sits at depth 1, the key is on the allow-list, the value is a string of 1 to
# 64 characters from [A-Za-z0-9._:-] (any backslash disqualifies it), and the key was not seen before.
readonly AWK_TOP='
BEGIN { RS = "\""; depth = 0; instr = 0; acc = ""; esc = 0; haspend = 0; pend = ""; isval = 0 }
function allowed(k) { return k ~ /^(session_id|hook_event_name|source|reason|agent_id|agent_type|id)$/ }
{
  r = $0
  if (!instr) {
    t = r
    sub(/^.*[,[{]/, "", t)
    isval = (t ~ /:/)
    o = gsub(/[[{]/, "&", r)
    c = gsub(/[]}]/, "&", r)
    depth += o - c
    instr = 1
    next
  }
  if (match(r, /\\+$/) && (RLENGTH % 2 == 1)) { acc = acc r "\""; esc = 1; next }
  content = acc r
  bad = esc || (content ~ /\\/)
  acc = ""; esc = 0; instr = 0
  if (depth != 1) next
  if (isval) {
    if (haspend && !bad && length(content) >= 1 && length(content) <= 64 && content ~ /^[A-Za-z0-9._:-]+$/ && !(pend in seen)) {
      seen[pend] = 1
      print pend "=" content
    }
    haspend = 0
  } else {
    haspend = (!bad && allowed(content))
    pend = content
  }
}'

# top_pairs STRING -> `key=value` lines for the allowed top-level members of the single-line JSON.
top_pairs() { printf '%s' "$1" | LC_ALL=C awk "$AWK_TOP"; }

# pair_get PAIRS KEY -> the value, or nothing.
pair_get() {
  local t v
  t=$'\n'$1
  v=${t#*$'\n'"$2"=}
  if [ "$v" = "$t" ]; then return 0; fi
  printf '%s' "${v%%$'\n'*}"
}

mint_uuid() { # canonical version-4 UUID -> UUID
  local hex n i variants=89ab
  hex=$(od -An -N16 -tx1 /dev/urandom)
  hex=${hex//[[:space:]]/}
  if [[ ! $hex =~ ^[0-9a-f]{32}$ ]]; then
    hex=
    for i in 1 2 3 4 5 6 7 8; do
      printf -v n '%04x' $((RANDOM * 2 + RANDOM % 2))
      hex+=$n
    done
  fi
  n=$((16#${hex:16:1} & 3))
  UUID="${hex:0:8}-${hex:8:4}-4${hex:13:3}-${variants:n:1}${hex:17:3}-${hex:20:12}"
}

# ---------------------------------------------------------------- per-session state

read_state() { # -> S_OK S_RUN S_RT S_HB
  local f="$STATE_DIR/$SESSION_ID" a= b= c=
  S_OK=0 S_RUN= S_RT= S_HB=0
  [ -f "$f" ] || return 1
  IFS=' ' read -r a b c <"$f"
  [[ $a =~ $UUID_RE ]] || return 1
  [[ $b =~ $UUID_RE || $b == - ]] || return 1
  [[ $c =~ ^[0-9]{1,12}$ ]] || return 1
  S_OK=1 S_RUN=$a S_RT=$b S_HB=$c
}

# Atomic (temp file, then rename): hooks run in parallel, so a reader must never see a
# half-written file.
write_state() { # run runtime-or-dash heartbeat-epoch
  local tmp="$STATE_DIR/.$SESSION_ID.$$.tmp"
  mkdir -p "$STATE_DIR" || return 1
  if printf '%s %s %s\n' "$1" "$2" "$3" >"$tmp"; then
    mv -f "$tmp" "$STATE_DIR/$SESSION_ID" || rm -f "$tmp"
  else
    rm -f "$tmp"
  fi
}

# ---------------------------------------------------------------- transport

# The key file is parsed, never sourced: anything that can write it (or a shell `cat` of it) is
# outside what this script can defend, so at least nothing in it is ever executed. Only the first
# `DAYTHREE_TWIN_BASE_URL=` and `DAYTHREE_TWIN_KEY=` lines count; every other line is ignored.
load_config() {
  local host line
  TW_BASE_URL= TW_KEY=
  if [ -f "$KEY_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line=${line//$'\r'/} # a key file saved by a Windows editor
      case $line in
        DAYTHREE_TWIN_BASE_URL=*) if [ -z "$TW_BASE_URL" ]; then TW_BASE_URL=${line#*=}; fi ;;
        DAYTHREE_TWIN_KEY=*) if [ -z "$TW_KEY" ]; then TW_KEY=${line#*=}; fi ;;
      esac
    done <"$KEY_FILE"
  fi
  if [ -z "$TW_BASE_URL" ] || [ -z "$TW_KEY" ]; then finish no_key; fi
  TW_BASE_URL=${TW_BASE_URL%/}
  if [[ ! $TW_KEY =~ $KEY_RE ]] || [[ ! $TW_BASE_URL =~ $URL_RE ]]; then finish bad_config; fi
  host=${BASH_REMATCH[2]}
  LOOPBACK=
  case $host in localhost | 127.0.0.1 | '[::1]') LOOPBACK=1 ;; esac
  if [ "${BASH_REMATCH[1]}" = http ] && [ -z "$LOOPBACK" ]; then finish insecure_transport; fi
  CURL_OPTS=(--connect-timeout 1 --max-redirs 0 --proto '=http,https' --path-as-is --max-filesize 65536)
  if [ -n "$LOOPBACK" ]; then CURL_OPTS+=(--noproxy '*'); fi
  CONFIG_OK=1
}

# api_call METHOD PATH JSON-BODY -> HTTP_CODE RESP. The curl configuration (URL, headers,
# body, and therefore the key) goes to curl on stdin, so the key is in no argv and no
# environment. One retry only on a connection failure or a 5xx.
#
# Time budget: the hook has 5 s in total, and its login shell has already used part of that
# before this script starts, so this script spends at most 4 s. Every attempt is capped at
# `--max-time min(2, 4 - elapsed)` and may not start once 3 s are gone; a RETRY of the same
# request may only start in the first 2 s, so a platform that hangs costs one 2 s attempt, not
# two. (A blanket `elapsed < 2` for every attempt would starve the 409 recovery chain on a slow
# Windows machine, where its three calls take about 3 s.)
api_call() {
  local method=$1 path=$2 body=$3 attempt=0 out rc code esc cfg budget
  HTTP_CODE=000 RESP=
  if [ "${TWIN_DRY_RUN:-}" = 1 ]; then
    if [ -n "${TWIN_DRY_RUN_FILE:-}" ]; then printf '%s %s %s\n' "$method" "$path" "$body" >>"$TWIN_DRY_RUN_FILE"; fi
    if [ "$method" = POST ] && [ "$path" = /api/v1/agent-runtime/sessions ]; then
      mint_uuid
      HTTP_CODE=201 RESP="{\"id\":\"$UUID\"}"
    else
      HTTP_CODE=200 RESP='{}'
    fi
    return 0
  fi
  if [ -z "$CONFIG_OK" ]; then load_config; fi
  esc=${body//\"/\\\"}
  printf -v cfg 'url = "%s%s"\nrequest = "%s"\nheader = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\ndata = "%s"\n' \
    "$TW_BASE_URL" "$path" "$method" "$TW_KEY" "$esc"
  while [ "$attempt" -lt 2 ]; do
    budget=$((4 - SECONDS))
    if [ "$budget" -lt 1 ]; then break; fi
    if [ "$attempt" -ge 1 ] && [ "$SECONDS" -ge 2 ]; then break; fi
    if [ "$budget" -gt 2 ]; then budget=2; fi
    attempt=$((attempt + 1))
    out=$(printf '%s' "$cfg" | curl -q -s -K - "${CURL_OPTS[@]}" --max-time "$budget" -w '%{http_code}')
    rc=$?
    code=${out: -3}
    if [ "$rc" -eq 0 ] && [[ $code =~ ^[0-9]{3}$ ]]; then
      HTTP_CODE=$code RESP=${out%???}
      case $code in 5??) ;; *) return 0 ;; esac
    else
      HTTP_CODE=000 RESP=
    fi
  done
  return 0
}

class_for_code() {
  case $1 in
    2??) CLASS=ok ;;
    4??) CLASS=client_error ;;
    5??) CLASS=server_error ;;
    000) CLASS=conn_fail ;;
    *) CLASS=unexpected ;;
  esac
}

# fail_from_response: log the class for the last response and exit.
fail_from_response() { class_for_code "$HTTP_CODE"; finish "$CLASS" "$HTTP_CODE"; }

register_session() { # run-uuid -> REG_RT ; 0 on a 2xx carrying a valid runtime id
  local body
  REG_RT=
  printf -v body '{"kind":"session","external_session_ref":"%s"}' "$1"
  api_call POST /api/v1/agent-runtime/sessions "$body"
  case $HTTP_CODE in 2??) ;; *) return 1 ;; esac
  REG_RT=$(pair_get "$(top_pairs "${RESP//$'\n'/ }")" id)
  if [[ ! $REG_RT =~ $UUID_RE ]]; then REG_RT= HTTP_CODE=000; return 1; fi
  return 0
}

# State exists but the session never registered (the platform was unreachable at start, so
# the state has no runtime id): re-POST the SAME minted run uuid already in that state, at
# most once per invocation. The server is idempotent on that ref, so this can never create a
# second Mission. Never called when there is no state file (that is a logged miss, T3-F12),
# and never by a heartbeat that already has a runtime id. The attempt is stamped in the state
# BEFORE the call and stays stamped on failure, so an outage costs one slow call per throttle
# window (300 s on a heartbeat, 60 s on a subagent start), not one per event.
ensure_session() {
  now_epoch
  write_state "$S_RUN" - "$NOW"
  if register_session "$S_RUN"; then
    S_RT=$REG_RT
    now_epoch
    write_state "$S_RUN" "$S_RT" "$NOW"
  else
    fail_from_response
  fi
}

# ---------------------------------------------------------------- event handlers

on_session_start() {
  local source run
  source=$(pair_get "$PAIRS" source)
  case $source in startup | resume | clear | compact | fork) ;; *) finish bad_source ;; esac
  read_state
  if [ "$source" = compact ] && [ "$S_OK" = 1 ]; then LOG_REF=$S_RUN; finish reused; fi
  if [ "$source" = startup ] && [ "$S_OK" = 1 ]; then
    LOG_REF=$S_RUN
    if [ "$S_RT" != - ]; then finish duplicate; fi
    run=$S_RUN
  else
    mint_uuid
    run=$UUID
  fi
  LOG_REF=$run
  if register_session "$run"; then
    now_epoch
    write_state "$run" "$REG_RT" "$NOW"
    finish ok "$HTTP_CODE"
  fi
  class_for_code "$HTTP_CODE"
  now_epoch
  case $CLASS in conn_fail | server_error) write_state "$run" - "$NOW" ;; esac
  finish "$CLASS" "$HTTP_CODE"
}

post_subagent() { # instance-ref run-uuid agent-type-json-fragment
  local body
  printf -v body '{"kind":"subagent","external_instance_ref":"%s","parent_external_session_ref":"%s"%s}' "$1" "$2" "$3"
  api_call POST /api/v1/agent-runtime/sessions "$body"
}

on_subagent_start() {
  local ref type frag=
  ref=$(pair_get "$PAIRS" agent_id)
  if [[ ! $ref =~ $REF_RE ]]; then finish bad_ref; fi
  LOG_REF=$ref
  type=$(pair_get "$PAIRS" agent_type)
  # Only the five roster names are ever sent; anything else is omitted and the server
  # buckets it to the general persona (D38).
  if [[ $type =~ ^[a-z-]{1,32}$ ]] && [[ $ROSTER == *" $type "* ]]; then frag=",\"agent_type\":\"$type\""; fi
  # No state means SessionStart never ran for this session (hooks added mid-session, or the
  # state was lost): log a miss and send nothing. A session is never registered from a
  # subagent event.
  if ! read_state; then finish no_state; fi
  if [ "$S_RT" = - ]; then
    # The session never registered. Retry that at most once a minute: while the platform is
    # down, each subagent start must not add another slow call.
    now_epoch
    elapsed=$((NOW - 10#$S_HB))
    if [ "$elapsed" -ge 0 ] && [ "$elapsed" -lt 60 ]; then finish backoff; fi
    ensure_session
  fi
  post_subagent "$ref" "$S_RUN" "$frag"
  case $HTTP_CODE in
    2??) finish ok "$HTTP_CODE" ;;
    409)
      if [[ $RESP != *'"parent_session_ended"'* ]]; then fail_from_response; fi
      # The run ended (e.g. SessionEnd, or the reaper): move to a new run and retry this
      # subagent exactly once. A second refusal is terminal, never a loop. A parallel hook may
      # have moved the session to a new run already: read the state again and reuse that run
      # instead of minting a second one (which would create a second Mission).
      refused=$S_RUN
      if read_state && [ "$S_RUN" != "$refused" ] && [ "$S_RT" != - ]; then
        new_run=$S_RUN
      else
        mint_uuid
        new_run=$UUID
        if ! register_session "$new_run"; then fail_from_response; fi
        now_epoch
        write_state "$new_run" "$REG_RT" "$NOW"
      fi
      post_subagent "$ref" "$new_run" "$frag"
      case $HTTP_CODE in 2??) finish reregistered "$HTTP_CODE" ;; esac
      fail_from_response
      ;;
    *) fail_from_response ;;
  esac
}

on_subagent_stop() {
  local ref
  ref=$(pair_get "$PAIRS" agent_id)
  if [[ ! $ref =~ $REF_RE ]]; then finish bad_ref; fi
  LOG_REF=$ref
  # Declared, not measured: the payload carries no outcome and no tool-call count, so the
  # hook reports a completed close with a fixed reason and nothing else.
  api_call POST "/api/v1/agent-runtime/subagents/$ref/close" '{"outcome":"completed","reason_code":"hook_reported"}'
  case $HTTP_CODE in
    2??) finish ok "$HTTP_CODE" ;;
    404) finish close_miss 404 ;; # never register-then-close
    *) fail_from_response ;;
  esac
}

on_heartbeat() {
  local elapsed
  if ! read_state; then finish no_state; fi
  LOG_REF=$S_RUN
  now_epoch
  elapsed=$((NOW - 10#$S_HB))
  if [ "$elapsed" -ge 0 ] && [ "$elapsed" -lt "$HEARTBEAT_SECONDS" ]; then finish throttled; fi
  if [ "$S_RT" = - ]; then
    ensure_session # stamps the attempt first; a successful registration counts as the heartbeat
    finish ok "$HTTP_CODE"
  fi
  # Stamp the attempt, not the success: a platform outage must not add a slow call to every
  # prompt. The reaper window (2 hours) is far longer than this interval. Re-read first: a
  # SessionEnd or a re-registration that ran in parallel must not be overwritten.
  local run=$S_RUN
  if ! read_state || [ "$S_RUN" != "$run" ]; then finish no_state; fi
  write_state "$S_RUN" "$S_RT" "$NOW"
  api_call PATCH "/api/v1/agent-runtime/sessions/$S_RT" '{}'
  case $HTTP_CODE in 2??) finish ok "$HTTP_CODE" ;; esac
  fail_from_response
}

on_session_end() {
  local reason outcome
  reason=$(pair_get "$PAIRS" reason)
  # Fixed table; the raw reason is never forwarded.
  case $reason in
    clear | resume | logout | prompt_input_exit) outcome=completed ;;
    *) outcome=abandoned ;;
  esac
  CLEANUP_STATE=1 # the state file goes on every path from here, even a corrupt one
  if ! read_state; then finish no_state; fi
  LOG_REF=$S_RUN
  if [ "$S_RT" = - ]; then finish no_state; fi
  api_call PATCH "/api/v1/agent-runtime/sessions/$S_RT" "{\"outcome\":\"$outcome\"}"
  case $HTTP_CODE in 2??) finish ok "$HTTP_CODE" ;; esac
  fail_from_response
}

# ---------------------------------------------------------------- main

# Bounded read: at most 1 MiB and 2 seconds, kept in an unexported variable, never written
# to disk. `timeout 2 head -c` is the fast path. Measured on the operator's Windows Git Bash
# 5.2: `read` on a pipe manages about 30 KB/s (61 KB in the 2 s budget), because bash reads a
# pipe one byte at a time, so a 50 KB prompt would stall Claude Code for the whole timeout.
# `read -r -t 2` (the plan's mechanism) stays as the fallback when the fast path yields nothing.
payload=$(
  timeout 2 head -c $((MAX_PAYLOAD + 1))
  printf x
)
payload=${payload%x} # the sentinel keeps trailing newlines from hiding an over-limit read
if [ -z "$payload" ]; then IFS= read -r -t 2 -d '' -n $((MAX_PAYLOAD + 1)) payload; fi
if [ "${#payload}" -gt "$MAX_PAYLOAD" ]; then payload=; finish oversize; fi
if [ -z "$payload" ]; then finish empty; fi
payload=${payload//$'\r'/}
FLAT=${payload//$'\n'/ }
payload=
PAIRS=$(top_pairs "$FLAT")
FLAT=

EVENT_RAW=$(pair_get "$PAIRS" hook_event_name)
if [ -z "$EVENT_RAW" ]; then EVENT_RAW=${1:-}; fi
case $EVENT_RAW in
  SessionStart | SessionEnd | SubagentStart | SubagentStop | Stop | UserPromptSubmit) EVENT=$EVENT_RAW ;;
  '') finish bad_event ;;
  *) finish ignored ;;
esac

SESSION_ID=$(pair_get "$PAIRS" session_id)
if [[ ! $SESSION_ID =~ $UUID_RE ]]; then SESSION_ID=; finish bad_session; fi

case $EVENT in
  SessionStart) on_session_start ;;
  SubagentStart) on_subagent_start ;;
  SubagentStop) on_subagent_stop ;;
  SessionEnd) on_session_end ;;
  Stop | UserPromptSubmit) on_heartbeat ;;
esac
finish ok
