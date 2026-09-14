"""Agent Runtime (spec §10): the `AgentRuntimeAdapter` Protocol plus the Phase 0
durable adapter. The Mission Engine only ever imports the protocol + contracts —
never `DurableAgentRuntimeAdapter` directly by class name in its type hints — so a
LangGraph-backed adapter can be swapped in later (see docs/adr/ADR-004).
"""
