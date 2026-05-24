"""Quick API smoke test — run while uvicorn is live on port 8000."""
import urllib.request
import urllib.parse
import json, sys

BASE = "http://127.0.0.1:8000"
PASS = 0; FAIL = 0

def req(method, path, body=None, form=False):
    url = BASE + path
    if body and form:
        data = urllib.parse.urlencode(body).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    elif body:
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
    else:
        data, headers = None, {}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def check(label, method, path, body=None, form=False, expect=(200,201,202)):
    global PASS, FAIL
    code, body_resp = req(method, path, body, form)
    ok = code in expect
    status = "PASS" if ok else "FAIL"
    print(f"  {status} [{code}] {method} {path}")
    if not ok:
        print(f"       {body_resp[:200]}")
        FAIL += 1
    else:
        PASS += 1
    return code, body_resp

# ── Health ──────────────────────────────────────────────────────────────────
print("\n── Health ──")
check("live",  "GET", "/health/live")
check("ready", "GET", "/health/ready")

# ── Borrowers ───────────────────────────────────────────────────────────────
print("\n── Borrowers ──")
check("list borrowers", "GET", "/api/v1/borrowers")
_, raw = check("create borrower", "POST", "/api/v1/borrowers", {
    "external_id": "SMOKE-001", "phone": "+12025559999",
    "first_name": "Alice", "last_name": "Test",
    "time_zone": "America/Chicago", "preferred_language": "en",
    "original_creditor": "Smoke Bank",
    "principal_amount": 3000.00, "current_balance": 2900.00,
    "days_past_due": 30, "debt_type": "credit", "consent_recorded": True
}, expect=(201,409))
try:
    bid = json.loads(raw)["id"]
except Exception:
    bid = None
    # try fetching existing if 409
    _, lst = req("GET", "/api/v1/borrowers")
    items = json.loads(lst)
    bid = items[0]["id"] if items else None

if bid:
    check("get borrower",    "GET",   f"/api/v1/borrowers/{bid}")
    check("patch borrower",  "PATCH", f"/api/v1/borrowers/{bid}", {"days_past_due": 90})
    check("opt-out",         "POST",  f"/api/v1/borrowers/{bid}/opt-out",
          {"reason": "cease_and_desist", "channel": "phone"})
    check("404 borrower",    "GET",   "/api/v1/borrowers/00000000-0000-0000-0000-000000000000", expect=(404,))

# ── Campaigns ───────────────────────────────────────────────────────────────
print("\n── Campaigns ──")
check("list campaigns", "GET", "/api/v1/campaigns")
_, raw = check("create campaign", "POST", "/api/v1/campaigns", {
    "name": "Smoke Campaign", "strategy_type": "negotiation",
    "max_attempts": 3, "call_window_start": "09:00", "call_window_end": "17:00",
    "allowed_days": [1,2,3,4,5], "retry_interval_hrs": 24, "settlement_floor_pct": 0.7
}, expect=(201,))
try:
    cid = json.loads(raw)["id"]
except Exception:
    cid = None
if cid:
    check("get campaign",  "GET",  f"/api/v1/campaigns/{cid}")
    if bid:
        check("add borrower", "POST", f"/api/v1/campaigns/{cid}/borrowers",
              {"borrower_ids": [bid], "priority": 1}, expect=(201,))
    check("start campaign", "POST", f"/api/v1/campaigns/{cid}/start")
    check("start again (422)", "POST", f"/api/v1/campaigns/{cid}/start", expect=(422,))

# ── Calls ───────────────────────────────────────────────────────────────────
print("\n── Calls ──")
check("list calls", "GET", "/api/v1/calls")

# ── Analytics ───────────────────────────────────────────────────────────────
print("\n── Analytics ──")
check("dashboard",    "GET", "/api/v1/analytics/dashboard")
check("call-quality", "GET", "/api/v1/analytics/call-quality")

# ── Compliance ──────────────────────────────────────────────────────────────
print("\n── Compliance ──")
if bid:
    check("compliance events", "GET", f"/api/v1/compliance/events/{bid}")

# ── Telephony webhooks (form-encoded) ───────────────────────────────────────
print("\n── Telephony Webhooks ──")
check("voice webhook",      "POST", "/api/v1/telephony/voice",
      {"CallSid": "CAtest001", "From": "+12025559999", "To": "+12138387179", "CallStatus": "in-progress"},
      form=True)
check("status_callback",    "POST", "/api/v1/telephony/status_callback",
      {"CallSid": "CAtest001", "CallStatus": "completed", "CallDuration": "45"},
      form=True)
check("recording_callback", "POST", "/api/v1/telephony/recording_callback",
      {"CallSid": "CAtest001", "RecordingUrl": "https://api.twilio.com/rec/RE001", "RecordingDuration": "45"},
      form=True)

print(f"\n{'='*40}")
print(f"  Results: {PASS} PASS / {FAIL} FAIL")
print(f"{'='*40}\n")
sys.exit(0 if FAIL == 0 else 1)
