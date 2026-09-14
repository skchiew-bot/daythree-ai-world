"""Platform- and tenant-scope default tool policies (spec §12).

Phase 0 has no admin UI for platform/tenant-level tool configuration, so these are
fixed constants rather than DB rows — both default to "allow everything", which means
the *agent version's* tool policy (configured per agent, e.g. Atlas's) is the scope
that actually narrows access in Phase 0. Making these tenant/platform policies
DB-configurable is reasonable Phase 1 scope, not a Phase 0 requirement.
"""
from __future__ import annotations

from contracts.policy import ToolPolicy

PLATFORM_DEFAULT_TOOL_POLICY = ToolPolicy(allow=["*"], deny=[])
TENANT_DEFAULT_TOOL_POLICY = ToolPolicy(allow=["*"], deny=[])
