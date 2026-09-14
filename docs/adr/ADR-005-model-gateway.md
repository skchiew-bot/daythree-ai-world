# ADR-005: Model Gateway

## Context

Spec §11 forbids the Mission Engine from ever calling a model provider directly and
assigns the gateway routing, retries, timeout, token limits, cost ceiling, telemetry,
error normalization, a circuit breaker, and request/response hashing.

## Options Considered

1. A single `ModelGateway` class (`services/model-gateway/model_gateway/gateway.py`)
   owning retry/timeout/circuit-breaker/budget-check/hashing, with providers as
   interchangeable `ModelProvider` implementations behind a plain dict lookup by name.
2. A heavier routing layer (e.g. LiteLLM or a custom multi-provider router with
   weighted/fallback routing across several live providers).

## Decision

Option 1. Three providers are implemented: `MockModelProvider` (default, zero external
dependencies, deterministic schema-valid output), `AnthropicProvider`, and `OpenAIProvider`
(both real, each gated on its own API key — `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — being
non-empty). `OpenAIProvider` uses the Chat Completions API (not Responses) for parity with
`AnthropicProvider`'s shape — one system message, one user message, one response — and
defaults to `gpt-4o-mini` for the demonstration mission as the cheaper of the two real
providers to smoke-test with. CI's `e2e-and-resilience` job can run the spec §19
demonstration mission against the real OpenAI provider via a `workflow_dispatch` input
(`real_model_provider: openai`), gated on the `OPENAI_API_KEY` repository secret — never
automatic on a push or PR, so no CI run spends real API money without a human explicitly
asking for that run.

## Rationale

- Phase 0 has exactly one model policy per agent version and no requirement for
  multi-provider fallback routing (spec §3 excludes "autonomous investment committee"-
  style complexity, and nothing in §11 asks for cross-provider fallback specifically) —
  a routing library would add configuration surface with no Phase 0 consumer.
- The **budget check happens inside `ModelGateway.generate()`, before the provider is
  ever called** (`policy_sdk.budgets.evaluate_budget`) — this is what makes "budget
  enforcement happens before each invocation" (spec §22) literally true rather than an
  after-the-fact accounting exercise.
- The circuit breaker (`routing/circuit_breaker.py`) is intentionally minimal: a
  per-provider consecutive-failure counter with a cooldown, no half-open probe queue.
  Enough to stop a Phase 0 mission from hammering a clearly-down provider; a
  production-grade breaker (sliding window, jittered backoff, per-model granularity) is
  a reasonable Phase 1 upgrade once there's real multi-provider traffic to observe.
- `MockModelProvider` exists specifically so the entire walking skeleton — including the
  demonstration mission in spec §19 — is provable with **zero external dependencies and
  zero cost**, while `AnthropicProvider` proves the "real production provider adapter"
  requirement (spec §31 STEP 6) without forcing every dev/CI run to hold a live API key.

## Consequences

- Pricing (`model_gateway/telemetry.py`'s `_PRICING_PER_1K_TOKENS` table) is a flat,
  hand-maintained table, not a live pricing API call — acceptable for Phase 0's cost-
  ceiling enforcement (which only needs to be directionally correct and consistent), not
  billing-grade.
- Retry count and circuit-breaker state are **in-process** (not shared across worker
  replicas via Redis) — fine for Phase 0's single-worker deployment; a multi-replica
  worker fleet would want a shared breaker state, a Phase 1 concern.

## Rollback Path

Add a third `ModelProvider` implementation (OpenAI, Gemini, DeepSeek, a local model
server) and register it in `services/worker/deps.py::build_model_gateway` — no change
needed to `ModelGateway`, the Mission Engine, or the Agent Runtime, since all three only
depend on the `ModelProvider` protocol and `ModelRequest`/`ModelResponse` contracts.
