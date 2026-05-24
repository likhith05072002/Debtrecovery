# Import all models so SQLAlchemy mapper registry is fully populated
from app.models.database.borrower import Borrower
from app.models.database.call import Call
from app.models.database.call_analysis import CallAnalysis
from app.models.database.campaign import Campaign, CampaignBorrower
from app.models.database.compliance import ComplianceEvent
from app.models.database.conversation import ConversationTurn, BehavioralEvent, RepaymentPromise
from app.models.database.human_call import HumanCall
from app.models.database.ml_outcome import MLCallOutcome
from app.models.database.organization import Organization
from app.models.database.user import User, APIKey, Invitation
from app.models.database.billing import Subscription, UsageRecord, PlanLimit, Invoice
from app.models.database.webhook import Webhook, WebhookDelivery, AuditLog, ScheduledReport, WhiteLabelConfig
from app.models.database.onboarding import OnboardingProgress, MarketplaceTemplate

__all__ = [
    "Borrower",
    "Call",
    "CallAnalysis",
    "Campaign",
    "CampaignBorrower",
    "ComplianceEvent",
    "ConversationTurn",
    "BehavioralEvent",
    "HumanCall",
    "RepaymentPromise",
    "MLCallOutcome",
    "Organization",
    "User",
    "APIKey",
    "Invitation",
    "Subscription",
    "UsageRecord",
    "PlanLimit",
    "Invoice",
    "Webhook",
    "WebhookDelivery",
    "AuditLog",
    "ScheduledReport",
    "WhiteLabelConfig",
    "OnboardingProgress",
    "MarketplaceTemplate",
]
