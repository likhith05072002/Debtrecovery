"""
Seed the database with sample borrowers for development and testing.

Usage:
    python scripts/seed_borrowers.py [--count 20]
"""
from __future__ import annotations

import argparse
import asyncio
import random
import uuid
from decimal import Decimal

FIRST_NAMES = ["John", "Sarah", "Michael", "Emily", "David", "Lisa", "Robert", "Karen"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller"]
DEBT_TYPES = ["credit_card", "medical", "auto", "personal", "student"]
CREDITORS = ["Capital One", "Chase Bank", "Bank of America", "Citibank", "Wells Fargo", "Synchrony"]


async def seed(count: int) -> None:
    from app.models.database.base import AsyncSessionLocal, engine, Base
    from app.models.database.borrower import Borrower
    from app.utils.crypto import encrypt_pii, hash_pii

    # Create tables in dev
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        for i in range(count):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            phone = f"+1{random.randint(2000000000, 9999999999)}"
            balance = Decimal(str(round(random.uniform(500, 15000), 2)))
            dpd = random.randint(0, 180)

            borrower = Borrower(
                external_id=f"SEED-{uuid.uuid4().hex[:8].upper()}",
                phone_e164=encrypt_pii(phone),
                phone_hash=hash_pii(phone),
                first_name=first,
                last_name=last,
                time_zone=random.choice(["America/New_York", "America/Chicago", "America/Los_Angeles"]),
                original_creditor=random.choice(CREDITORS),
                principal_amount=balance * Decimal("1.1"),
                current_balance=balance,
                days_past_due=dpd,
                debt_type=random.choice(DEBT_TYPES),
                consent_recorded=True,   # All seeds have consent for dev
            )
            db.add(borrower)
            print(f"Added: {first} {last} | ${balance} | {dpd} DPD | {phone}")

        await db.commit()
        print(f"\n✓ Seeded {count} borrowers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(seed(args.count))
