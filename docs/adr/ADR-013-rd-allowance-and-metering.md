# ADR-013: Self-Directed R&D Allowance and AI-Token Metering

Status: **Accepted for planning** (2026-09-18). Council convened, gate review and data-warden
conditions folded in. No implementation has started. Executable phases `R0` to `R4` and `W1` are in
`docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`. Builds on ADR-011 (ledger) and ADR-012.

## Context

Operator intent (Chiew Sin Kwang, 2026-09-18, verbatim): "I want the AI agent to continuously learn
new items based on their digital earnings they have to exchange for real world AI token to be used to
learn or RnD on their own accord. Any task assigned to them from the real world, the AI token
consumption will be borne by the real-world and of course being metered and monitored to ensure the
digital twin does not use the AI token without control." In the same message: the 3D world should be
"more graphically nicer" with agents visibly "moving around in the digital world especially when they
are idle."

Facts in current code that decide the shape of this ADR (each verified by the chair at the cited
lines on 2026-09-18):

- **The per-task budget does not enforce cost, calls or runtime today.**
  `services/agent-runtime/agent_runtime/adapters/durable_adapter.py` line 128 passes a fresh
  `BudgetUsage()` (all zeros) to the gateway on every call; `packages/policy-sdk/policy_sdk/budgets.py`
  lines 36 to 47 compare `calls_made`, `cost_spent_usd` and `elapsed_minutes` against that zero. Only
  the `max_output_tokens` check (line 49) can fire. No non-test code constructs a non-zero
  `BudgetUsage`.
- **One budget check, up to three billed attempts.** `services/model-gateway/model_gateway/gateway.py`
  line 59 evaluates the budget once; lines 72 to 103 then loop `max_attempts=3` provider calls with no
  re-evaluation and `is_retry` never set. A timeout at line 75 cancels the client coroutine after the
  provider has accepted the request, which bills anyway. `task_executor.py` runs a second full
  execute for output repair. Worst case: 6 billed calls under a policy that reads "6 calls, $2.00".
- **Cost is recorded only on success, and unknown models are priced as Sonnet.** Telemetry exists
  only on the success path (`gateway.py` lines 83 to 93); `telemetry.py` line 21 falls back to
  `_DEFAULT_PRICE = (0.003, 0.015)`, a 5x undercount for an unlisted Opus-class model.
- **`knowledge_read` cannot read artifacts and there is no tool loop.**
  `packages/tool-sdk/tool_sdk/tools.py` lines 62 to 70 look a key up in `context.available_context`,
  a dict copied from `task.input_context`, which `mission_service.py` always creates empty.
  `ToolRegistry` is never instantiated outside tests. `tool_policy` reaches the model only as prose.
- **Artifact reads are tenant-scoped, never agent-scoped** (`services/api/routes/artifacts.py`
  lines 35 and 51). **No `with_for_update` exists in the repo.** **`autonomy_level` is read by no
  enforcement path.** The worker's queue is a Redis list with no lease; a restarted worker requeues
  every `running` task globally.
- The platform meters real cost only for `custom_durable` agents. A Claude Code twin
  (`external_manual`) runs on the operator's subscription and its tokens are unobservable; ADR-011
  already labels such numbers "declared, not measured".
- Today no real provider key is configured and the default provider is `MockModelProvider`, so the
  defects above have cost nothing yet. They would cost real money on the first day an Anthropic key
  is set.

## Decision

Six parts, in dependency order. Nothing in parts 2 to 5 ships before part 1 is merged and proven.

1. **Make the existing budget real first (R0).** Thread cumulative usage (committed
   `model_invocations` plus checkpoint history) into the adapter; re-evaluate the budget inside the
   gateway retry loop with `is_retry=True`; treat a timeout as billed; write a `status=failed`
   invocation row for every failed or timed-out attempt; make an unpriced `(provider, model)` pair a
   hard error, never a default price; add an index on `model_invocations(tenant_id, agent_id,
   created_at)`. Exit test: a task with `max_model_calls=1` makes exactly one provider call across
   retries and repair. This is a defect fix to Phase 0 and is recorded as such in the completion
   report. **No real provider key is set in `.env` until R0 is merged**: operator decision O13
   makes OpenAI the worker's provider, so the first configured key is the first real spend.
2. **Meter before granting (R1).** Per-twin spend for the current period, derived from the now
   trustworthy rows, shown in the admin UI and the twin's room. For `external_manual` twins the
   figure is the declared flat fee and is labeled "declared, not measured"; declared numbers never
   enter minting, allowances or autonomy proposals.
3. **Credits unlock, never convert (R2).** The operator sets a real USD ceiling per period per tenant,
   optionally per agent, in `twin_rd_allowances`. A twin's available draw is a **step function** of
   credits earned in the trailing window over operator-defined bands (default 0 / 25% / 50% / 100% of
   the ceiling), declared in versioned config, with the ceiling always binding first. Credits are
   never debited, reserved or refunded by R&D; there is no rate, so there is no price and ADR-011's
   closed loop holds. The ADR's own test of this rule: if `f` can express a linear price, the design
   has failed. Spend is a **reservation**: before each call the worker debits the call's
   `max_model_cost_usd` from the period allowance inside a locked anchor row per
   `(tenant_id, agent_id, period)`, then trues up to actual cost afterwards; it fails closed.
4. **R&D runs only in the platform worker, started by a human (R3).** Any twin may write a proposal
   row in `twin_rd_proposals` (objective, expected artifact, requested budget, `risk_level` capped
   at low). A human-roled principal starts it at every autonomy level; the platform creates a
   mission assigned to a `custom_durable` version of the same persona under a `BudgetPolicy` bounded
   by the remaining allowance. `external_manual` twins never run R&D in their own session. Learning
   persists as `knowledge_note` artifacts; the platform injects the twin's own prior notes into
   `task.input_context` at mission creation through a server-side query with explicit
   `Artifact.agent_id == agent.id` and `tenant_id` predicates, where `knowledge_read` can reach
   them. No new tool, no artifact-route change, no cross-agent read, no web access.
5. **Bounded standing authorization, on evidence only (R4).** After R3 has closed real R&D missions,
   the operator may sign a revocable authorization (N missions, $X, expiry) recorded in
   `audit_events`; the worker executes proposals against it without a per-mission click. This
   delivers "on their own accord" without breaking charter rule 1, because recorded human approval
   exists, granted ahead of time and bounded. Kill switch: a Redis flag checked between dequeue and
   execute and before every provider attempt, plus the fail-closed reservation; zeroing a DB ceiling
   alone cannot stop in-flight work.
6. **The 3D world gets life without new data (W1).** Idle twins leave their room, walk the corridor
   and lobby, and return, driven only by the activity state and room assignment the world already
   polls. Richer geometry, lighting and materials are a rendering budget question. The render
   payload is an explicit field allow-list; no task title, mission objective, error string, note text
   or `job_description` is ever drawn on an avatar or tooltip. W1 has no dependency on the twin
   phases and may start now.

## Council (2026-09-18)

Convened per the `council` skill: three fresh voices with only the question and platform facts.

**Architect (in-context, written first):** yes, credits unlock an operator-set ceiling and never
convert; R&D only through the worker; Claude Code twins get R&D only by proposing a worker-run
mission. Risk named: R&D missions have no acceptance signal, so they can become a self-referential
spend loop, and "what the twin retains" is undefined in the schema.

**Skeptic:** reject "unlock a budget" as a second enforcement path layered on `BudgetPolicy`; one
ceiling, credits only move where it sits. Metering is unsatisfiable for Claude Code twins by
construction. With no memory store, funding R&D buys API calls that evaporate. Surprise: nobody has
said what R&D output would even mean.

**Pragmatist:** yes, reuse `BudgetPolicy`, `estimated_cost` and the circuit breaker with a `purpose`
discriminator; external twins get zero self-directed spend; start the ceiling absurdly low ($1 to
$2 per twin per week) and let data raise it. Surprise: the operator's review queue is the real
bottleneck; credits will pile up unspent, so instrument review latency first.

**Critic:** allow it as a one-way, rate-limited ceiling under the same gate real tasks use. The mint
side is the weak link: if declared cost ever fed minting, a twin would have an incentive to
over-report. Surprise: `knowledge_read` under a permissive `tool_policy` could read across agents.

### Verdict

- **Consensus:** one enforcement path, the existing `BudgetPolicy` made real; R&D only in the
  worker; `external_manual` twins get zero self-directed spend; tiny initial ceilings; declared
  numbers never feed minting or allowances.
- **Strongest dissent:** the Skeptic would not fund R&D at all until learning can persist. Accepted
  in part: `knowledge_note` persistence ships in the same phase as the first R&D mission (R3), and
  R2's allowance has nothing to draw against until R3 exists.
- **Premise check:** the Skeptic challenged "unlock". Kept as the operator-facing word, defined
  precisely as a stepped, ceiling-bound gate over money the operator already committed.
- **Recommendation changed by the council and gate:** the Architect's A2 auto-start is dropped (a
  human starts every R&D mission until R4's recorded standing authorization exists); R0 was added
  because no council voice knew the existing budget was a no-op until the gatekeeper read the
  adapter; review latency joins the Gate E instrumentation.

## Gate Review Outcome (guardian-gatekeeper, 2026-09-18)

Verdict on the brief: **BLOCK + ALTERNATIVE** on execution, metering, knowledge scoping and the kill
switch; "credits unlock, never convert" **passes** the no-fiat rule on the step-function condition.
The decision above is the alternative. Findings, verified by the chair where marked:

- **F1 CRITICAL (verified), budget enforces only output size.** `durable_adapter.py:128` zero
  `BudgetUsage`; `budgets.py:36-47`. *Adopted:* R0.
- **F2 CRITICAL (verified), retries and repair multiply spend.** `gateway.py:59` vs `72-103`;
  `task_executor.py` repair execute. *Adopted:* R0.
- **F3 HIGH (verified), `estimated_cost` untrustworthy.** Success-only telemetry; `_DEFAULT_PRICE`.
  *Adopted:* R0.
- **F4 HIGH, monthly ceiling as a post-hoc `SUM` is a lost update.** No `with_for_update` in the
  repo; no index on `model_invocations`. *Adopted:* reservation inside a locked anchor row (R2).
- **F5 HIGH, double spend through orphan requeue.** `queue.py` BRPOP without lease;
  `worker/main.py:26-35` global requeue. *Adopted:* R0 adds a worker lease or ownership check
  before any real key is configured.
- **F6 CRITICAL (verified), `knowledge_read` cannot read artifacts; no tool loop.** *Adopted:*
  server-side injection into `input_context` (R3). **Carried back to ADR-011:** part 4's "twins read
  the profile through the existing `knowledge_read` tool" is not implementable as written; M1 must
  use the same injection path.
- **F7 HIGH, artifact reads are tenant-scoped only.** `artifacts.py:35,51`. *Adopted:* agent_id
  predicate in the injection query and a cross-agent isolation test (R3).
- **F8 HIGH, A2 auto-start violates charter rule 1; `autonomy_level` is enforced nowhere; no
  non-human role exists.** *Adopted:* human start at every level (R3); bounded recorded
  authorization later (R4); the ADR states the line: a twin may write a proposal row; only a
  human-roled principal or a recorded, bounded operator authorization may cause execution.
- **F9 MEDIUM, kill switch cannot stop in-flight work.** *Adopted:* Redis flag at dequeue and per
  attempt, fail-closed reservation (R4).
- **F10 MEDIUM, mission shape.** One task per mission; no `missions.source` column. *Adopted:*
  `twin_rd_proposals` side table keyed by `mission_id`; R&D is one prompt and one completion per
  mission in R3, and a research loop is a later decision.

Conditions G1 to G10 map one-to-one and are restated as exit criteria in the build plan.

## Data-warden review (guardian-data-warden, 2026-09-18)

Verdict: **PASS WITH CONDITIONS D6 to D11**, continuing ADR-011's list. Confirmed in code that
`assembler.py:52-56` dumps `available_context` verbatim into the prompt, that `knowledge_read` has no
access control of its own, and that `sql_checkpoint_store.py:30-42` persists full prompts into
`runtime_checkpoints.state`.

- **D6.** The injection query filters `knowledge_note` by `agent_id` and `tenant_id`; a test proves a
  second agent's notes are absent from the first agent's context. The ACL lives at assembly time.
- **D7.** `knowledge_note` content is twin-authored free text under the same rule as D1/D2: never
  read verbatim by the council; any reporting or rendering of notes goes through a code-enforced
  redaction pass first.
- **D8.** Before operator-profile text or twin notes enter any R&D prompt, this ADR's build plan
  names the provider data-handling terms in force (retention, training opt-out, DPA reference).
- **D9.** `runtime_checkpoints.state` stays off every read path except checkpoint resume: no API
  route, no council read, no export.
- **D10.** R&D objectives, whoever writes them, follow D3's forbidden-content list.
- **D11.** The W1 render payload is built from an explicit allow-list (activity state, room, slot),
  with a test asserting its field set.

## Consequences

- R0 is a Phase 0 defect fix and is reported as one; the completion report's budget claims are
  corrected to say what was and was not enforced before R0.
- One additive migration (`0008_twin_rd`): `twin_rd_allowances`, `twin_rd_anchors`,
  `twin_rd_proposals`, plus the `model_invocations` index. No existing table gains a column.
- The operator gains three controls: a ceiling, a start button, and later a bounded standing
  authorization. Twins gain one: a proposal row.
- Every R&D screen shows real measured spend for worker-run twins and "declared, not measured" for
  Claude Code twins, side by side, so the difference is never hidden.
- Amendment to ADR-011 recorded here: M1's profile read uses server-side injection into
  `input_context`, not the `knowledge_read` tool as written.

## Operator decisions (Chiew Sin Kwang, 2026-09-19)

- **O10. Decided:** R0 ships now as a standalone fix PR, ahead of the twin phases.
- **O11. Decided:** initial R&D ceiling is $2 per twin per week.
- **O12. Decided:** step bands are 0 / 25 / 50 / 100% of the ceiling at 0 / 5 / 15 / 30 credits
  earned in the trailing 30 days.
- **O13. Decided:** the worker's provider is **OpenAI** (the operator holds an OpenAI account and
  key). No Anthropic API key is configured, so worker-run twins use OpenAI-provider model policies;
  `default_model_name` in `common/config.py` (`claude-sonnet-5`) is irrelevant once a policy names
  the model. Gemini is deferred until the operator has a key and a reason; adding it is its own
  small phase (provider class, price rows, registry entry, tests). The key lives only in the
  gitignored `.env` (compose passes `OPENAI_API_KEY` through), never in chat or a tracked file, and
  per decision 1 it is not set until R0 is merged. Data-warden D8 applies to OpenAI: its data-handling
  terms are written into `docs/operator/PROVIDER_TERMS.md` before any profile text or twin note
  enters a prompt. R&D missions default to the cheapest priced model configured.
- **O14. Decided:** W1 keeps the stylized apartment and adds lighting, materials, furniture, walk
  cycles and idle movement; W1 is independent of the twin phases and may start immediately, in
  parallel with R0 (disjoint files: frontend versus gateway and worker).

## Rollback Path

R0 is a fix and is not rolled back. R1 to R4 are additive behind `0008`; reverting their PRs and
running `downgrade()` leaves ADR-011 and ADR-012 intact. W1 is frontend-only and reverts with its PR.
