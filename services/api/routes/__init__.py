from fastapi import APIRouter, Depends

from api.dependencies.agent_runtime_auth import forbid_agent_runtime
from api.routes import (
    agent_rooms,
    agent_runtime,
    agents,
    artifacts,
    audit,
    auth,
    dashboard,
    external_agents,
    health,
    missions,
    model_invocations,
    model_policies,
    projects,
    tasks,
    tenant,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(agent_runtime.router)

# Default-deny for the agent_runtime credential (T1-F3): every OTHER router gets this
# extra dependency so a route added later inherits the refusal automatically instead of
# needing its own opt-out. `health`, `auth` and `agent_runtime` (above) are the only
# three routers this credential may ever reach.
_DENY_AGENT_RUNTIME = [Depends(forbid_agent_runtime)]

api_router.include_router(tenant.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(agents.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(agent_rooms.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(model_policies.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(missions.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(projects.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(tasks.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(artifacts.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(audit.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(dashboard.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(model_invocations.router, dependencies=_DENY_AGENT_RUNTIME)
api_router.include_router(external_agents.router, dependencies=_DENY_AGENT_RUNTIME)
