"""
GPT-4o function definitions for debt collection agent.
These are the only structured actions the AI can take during a call.
"""
from __future__ import annotations

FUNCTION_REGISTRY: list[dict] = [
    {
        "name": "record_promise",
        "description": "Record a repayment promise explicitly made by the borrower during this call. Call this as soon as the borrower commits to an amount and date.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Dollar amount promised (e.g. 150.00)"},
                "payment_date": {"type": "string", "format": "date", "description": "ISO 8601 date when payment will be made (e.g. 2026-04-01)"},
                "payment_method": {
                    "type": "string",
                    "enum": ["check", "ach", "card", "wire", "unknown"],
                    "description": "How the borrower will pay",
                },
            },
            "required": ["amount", "payment_date"],
        },
    },
    {
        "name": "trigger_opt_out",
        "description": "Borrower has clearly requested to stop all contact. Triggers immediate FDCPA opt-out processing and ends the call. Use when borrower says: 'stop calling', 'cease and desist', 'never contact me again', 'I'll sue you'.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Verbatim trigger phrase or reason"},
                "channel": {
                    "type": "string",
                    "enum": ["voice", "all"],
                    "description": "Which channels to opt out",
                },
            },
            "required": ["reason"],
        },
    },
    {
        "name": "log_dispute",
        "description": "Borrower is disputing the validity of the debt. This immediately stops all collection activity and flags the account for review.",
        "parameters": {
            "type": "object",
            "properties": {
                "dispute_reason": {"type": "string", "description": "Why the borrower says the debt is invalid"},
                "amount_disputed": {"type": "number", "description": "Dollar amount being disputed, if stated"},
            },
            "required": ["dispute_reason"],
        },
    },
    {
        "name": "request_callback",
        "description": "Borrower has requested a callback at a specific time. Schedule accordingly.",
        "parameters": {
            "type": "object",
            "properties": {
                "callback_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": "ISO 8601 datetime when borrower wants to be called back",
                },
                "preferred_number": {
                    "type": "string",
                    "description": "Alternative phone number if borrower specified one",
                },
            },
            "required": ["callback_time"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Transfer the call to a human agent. Use when: borrower is abusive, making legal threats, situation is complex, or borrower explicitly requests a human.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why escalation is needed"},
                "priority": {
                    "type": "string",
                    "enum": ["normal", "urgent"],
                    "description": "Urgency level — urgent for legal threats or extreme distress",
                },
            },
            "required": ["reason"],
        },
    },
    {
        "name": "end_call",
        "description": "End the call. Only call this in these specific situations: (1) borrower explicitly commits to a payment and record_promise was called, (2) borrower has refused at pressure_level 4 and refuses again, (3) borrower explicitly says 'hang up', 'end the call', or 'goodbye'. NEVER call this just because the introduction or mini-miranda was completed — that is the START of the call, not the end.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [
                        "promise_made",
                        "payment_arranged",
                        "refused",
                        "voicemail",
                        "callback_scheduled",
                        "opted_out",
                        "dispute_filed",
                        "escalated",
                        "no_outcome",
                    ],
                },
                "summary": {
                    "type": "string",
                    "description": "One-sentence summary of the call outcome for the record",
                },
            },
            "required": ["outcome"],
        },
    },
]
