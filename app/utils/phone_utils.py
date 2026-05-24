"""Phone number parsing and formatting utilities."""
from __future__ import annotations

import phonenumbers
from phonenumbers import PhoneNumberFormat


def normalize_e164(phone: str, default_region: str = "US") -> str:
    """Parse any phone string and return E.164 format (+12125551234)."""
    parsed = phonenumbers.parse(phone, default_region)
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(f"Invalid phone number: {phone}")
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def get_region(phone_e164: str) -> str | None:
    """Return the ISO 3166-1 alpha-2 country code for a phone number."""
    parsed = phonenumbers.parse(phone_e164, None)
    return phonenumbers.region_code_for_number(parsed)
