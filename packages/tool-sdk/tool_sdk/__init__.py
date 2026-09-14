"""The 4 Phase 0 tools (spec §12) and the registry that dispatches to them.

No tool here can touch the filesystem, run a shell command, or reach the open
internet — that's the whole point of Phase 0's tool allowlist being this short.
"""
