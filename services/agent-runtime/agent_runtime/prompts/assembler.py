"""Prompt assembly — spec §20. Every component is individually identifiable so the
assembled prompt's provenance (which template, which version, which hash) can be
traced later without re-deriving it, and the caller decides what's safe to log (spec
§20: "Do not blindly store sensitive assembled prompts in logs.") — this module never
logs anything itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from common.hashing import sha256_hex
from contracts.output_contract import OUTPUT_JSON_SCHEMA
from contracts.runtime import RunContext

PROMPT_TEMPLATE_ID = "phase0-single-task-research"
PROMPT_TEMPLATE_VERSION = "1.0"

SYSTEM_BASE_POLICY = (
    "You are operating inside Daythree AI World, a governed AI agent runtime. "
    "You must only use the tools explicitly listed under TOOL POLICY. Never invent "
    "evidence or claim access to information you were not given. If required "
    "information is unavailable, say so explicitly rather than guessing. Your final "
    "answer MUST be a single JSON object that validates against the OUTPUT CONTRACT "
    "schema below, and nothing else — no prose before or after the JSON."
)


@dataclass(frozen=True)
class PromptAssembly:
    template_id: str
    template_version: str
    system_prompt: str
    user_prompt: str
    system_prompt_hash: str
    user_prompt_hash: str
    assembled_prompt_hash: str


def assemble_prompt(context: RunContext) -> PromptAssembly:
    system_parts = [
        f"SYSTEM BASE POLICY:\n{SYSTEM_BASE_POLICY}",
        f"AGENT VERSION PROMPT:\n{context.system_prompt}",
        f"TOOL POLICY:\n{context.tool_policy.model_dump_json()}",
        f"BUDGET POLICY:\n{context.budget_policy.model_dump_json()}",
        f"OUTPUT CONTRACT (JSON Schema — your final answer must validate against this):\n"
        f"{json.dumps(OUTPUT_JSON_SCHEMA)}",
    ]
    system_prompt = "\n\n".join(system_parts)

    user_parts = [
        f"MISSION OBJECTIVE:\n{context.mission_objective}",
        f"TASK INSTRUCTIONS:\n{context.task_instructions}",
        f"AVAILABLE CONTEXT:\n{json.dumps(context.available_context)}",
    ]
    user_prompt = "\n\n".join(user_parts)

    system_hash = sha256_hex(system_prompt)
    user_hash = sha256_hex(user_prompt)

    return PromptAssembly(
        template_id=PROMPT_TEMPLATE_ID,
        template_version=PROMPT_TEMPLATE_VERSION,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        system_prompt_hash=system_hash,
        user_prompt_hash=user_hash,
        assembled_prompt_hash=sha256_hex(system_hash + user_hash),
    )
