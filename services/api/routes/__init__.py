from fastapi import APIRouter

from api.routes import (
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
    tasks,
    tenant,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tenant.router)
api_router.include_router(agents.router)
api_router.include_router(model_policies.router)
api_router.include_router(missions.router)
api_router.include_router(tasks.router)
api_router.include_router(artifacts.router)
api_router.include_router(audit.router)
api_router.include_router(dashboard.router)
api_router.include_router(model_invocations.router)
api_router.include_router(external_agents.router)
