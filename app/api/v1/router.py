from fastapi import APIRouter

from app.api.v1 import (
    auth,
    audit,
    billing,
    marketplace,
    onboarding,
    telephony,
    calls,
    borrowers,
    campaigns,
    analytics,
    compliance,
    human_calls,
    users,
    organizations,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(organizations.router, prefix="/org", tags=["organization"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
api_router.include_router(marketplace.router, prefix="/marketplace", tags=["marketplace"])
api_router.include_router(telephony.router, prefix="/telephony", tags=["telephony"])
api_router.include_router(calls.router, prefix="/calls", tags=["calls"])
api_router.include_router(borrowers.router, prefix="/borrowers", tags=["borrowers"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])
api_router.include_router(human_calls.router, prefix="/human-calls", tags=["human-calls"])
