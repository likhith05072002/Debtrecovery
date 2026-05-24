"""
Manually trigger a campaign run — dispatches all pending scheduled calls.

Usage:
    python scripts/run_campaign.py --campaign-id <UUID>
    python scripts/run_campaign.py --all      # dispatch all pending calls across all campaigns
"""
from __future__ import annotations

import argparse
import asyncio
import uuid


async def run(campaign_id: uuid.UUID | None, all_campaigns: bool) -> None:
    from app.models.database.base import AsyncSessionLocal
    from app.services.scheduling.campaign_runner import dispatch_pending_calls
    from sqlalchemy import select, update
    from app.models.database.campaign import Campaign, CampaignBorrower, CallSchedule
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        if campaign_id and not all_campaigns:
            # Schedule all pending borrowers in this campaign immediately
            result = await db.execute(
                select(CampaignBorrower).where(
                    CampaignBorrower.campaign_id == campaign_id,
                    CampaignBorrower.status == "pending"
                )
            )
            members = result.scalars().all()
            now = datetime.now(timezone.utc)
            for m in members:
                schedule = CallSchedule(
                    borrower_id=m.borrower_id,
                    campaign_id=campaign_id,
                    scheduled_at=now,
                    priority=m.priority,
                    attempt_number=m.attempts + 1,
                    status="pending",
                )
                db.add(schedule)
            await db.commit()
            print(f"Scheduled {len(members)} calls for campaign {campaign_id}")

        dispatched = await dispatch_pending_calls(db, limit=500)
        await db.commit()
        print(f"Dispatched {dispatched} calls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=str, default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    cid = uuid.UUID(args.campaign_id) if args.campaign_id else None
    asyncio.run(run(cid, args.all))
