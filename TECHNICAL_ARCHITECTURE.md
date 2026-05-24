# DebtCollector — Complete Technical Architecture

## What This System Does

DebtCollector is an AI voice agent that autonomously calls borrowers, negotiates debt repayment, and enforces FDCPA compliance in real time. It handles the full lifecycle: campaign scheduling → outbound dial → live conversation → post-call intelligence → borrower scoring → retry scheduling.

The system serves as a multi-tenant SaaS platform where collection agencies sign up, upload borrower portfolios, and let the AI agent make calls on their behalf.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Frontend (React 19 + TypeScript)              │
│  Login → Dashboard → Borrowers → Calls → Campaigns → Compliance     │
│  Billing → Team → API Keys → Onboarding Wizard                      │
└──────────────┬───────────────────────────────────────────────────────┘
               │ REST (JWT auth)
┌──────────────▼───────────────────────────────────────────────────────┐
│                     FastAPI Application (async)                       │
│                                                                       │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Auth    │ │ Calls    │ │Campaigns │ │Analytics │ │ Billing    │  │
│  │ Users   │ │Borrowers │ │Compliance│ │ Webhooks │ │ Marketplace│  │
│  │ Org     │ │HumanCalls│ │ Audit    │ │Onboarding│ │ Telephony  │  │
│  └─────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
│                                                                       │
│  ┌───────────────── WebSocket ─────────────────┐                     │
│  │  /ws/media/{call_sid}  — Twilio audio stream │                    │
│  │  Real-time bidirectional audio pipeline       │                    │
│  └───────────────────────────────────────────────┘                   │
└──────┬──────────┬──────────┬──────────┬──────────┬───────────────────┘
       │          │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼───┐ ┌───▼────┐ ┌───▼───┐
  │Postgres│ │ Redis  │ │Twilio │ │Deepgram│ │OpenAI │
  │  16    │ │  7     │ │ Voice │ │ STT    │ │GPT-4o │
  └────────┘ └────────┘ └───────┘ └────────┘ └───────┘
                                                  │
                                            ┌─────▼──────┐
                                            │ ElevenLabs │
                                            │    TTS     │
                                            └────────────┘
```

---

## 1. Call Lifecycle — End to End

### 1.1 Call Initiation

```
POST /api/v1/calls/initiate {borrower_id, campaign_id, language}
         │
         ▼
┌─ Endpoint: app/api/v1/calls.py ──────────────────────────┐
│  1. Authenticate user (JWT) → extract organization_id    │
│  2. Load borrower (org-scoped query)                     │
│  3. Check borrower.is_contactable (DNC/opt-out/bankruptcy)│
│  4. Update preferred_language if changed                  │
│  5. Call initiate_outbound_call()                         │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ Service: app/services/telephony/call_controller.py ─────┐
│  1. FDCPA pre-call compliance check:                      │
│     - Is borrower opted out?                              │
│     - Is borrower on DNC list (Redis)?                    │
│     - Call window check (8AM-9PM borrower local time)     │
│     - Consent recorded?                                   │
│  2. ML strategy selection:                                │
│     - XGBoost predicts: reminder/negotiation/settlement/  │
│       escalation/skip                                     │
│     - Falls back to rule-based if confidence < 0.45       │
│  3. Create Call record in PostgreSQL                      │
│  4. Store call setup metadata in Redis                    │
│  5. Twilio API: create outbound call                      │
│     - From: agency's Twilio number                        │
│     - To: borrower's phone (decrypted from Fernet)        │
│     - StatusCallback: /telephony/status                   │
│     - URL: /telephony/connect (returns TwiML)             │
│  6. Return 202 with call_id                               │
└──────────────────────┬───────────────────────────────────┘
                       ▼
         Twilio dials borrower's phone
                       │
         Borrower answers → Twilio opens WebSocket
```

### 1.2 WebSocket Audio Pipeline

When the borrower answers, Twilio opens a WebSocket to our server. This is the real-time audio pipeline — the most latency-critical code in the system.

```
┌─ WebSocket: app/api/websocket/media_stream.py ───────────────────────┐
│                                                                       │
│  EVENT: "start"                                                       │
│  ├─ Extract call_sid from Twilio custom parameters                   │
│  ├─ _initialize_call_session():                                       │
│  │   ├─ Load Call + Borrower from PostgreSQL                          │
│  │   ├─ Load call setup metadata from Redis                          │
│  │   ├─ Build BorrowerContext (name, balance, DPD, language, etc.)    │
│  │   ├─ Build CampaignContext (strategy, settlement floor, etc.)      │
│  │   ├─ Create SessionOrchestrator (the call state machine)           │
│  │   ├─ Create DeepgramStreamingClient (STT WebSocket)                │
│  │   ├─ Connect Deepgram → register on_transcript callback           │
│  │   └─ Start orchestrator greeting sequence                          │
│  └─ Enable AEC on barge-in detector                                   │
│                                                                       │
│  EVENT: "media" (every 20ms — 50 frames/second)                       │
│  ├─ Decode: base64 → mulaw bytes → PCM 16-bit                        │
│  ├─ Noise calibration (first 50 frames ≈ 1 second)                   │
│  ├─ Barge-in detection: orchestrator._barge_in.detect(pcm)            │
│  │   └─ If True → _interrupt_tts() + mark_audio_barge_in()           │
│  └─ Forward PCM to Deepgram: deepgram.send_audio(pcm)                │
│                                                                       │
│  CALLBACK: send_audio_to_twilio(mulaw_chunk)                          │
│  ├─ Feed outgoing audio to AEC as echo reference                     │
│  └─ Base64 encode → send via WebSocket to Twilio                     │
│                                                                       │
│  CALLBACK: clear_twilio_buffer()                                      │
│  └─ Send {"event": "clear"} to flush Twilio's audio queue            │
│                                                                       │
│  EVENT: "stop"                                                        │
│  └─ Trigger post-call analysis pipeline                               │
└───────────────────────────────────────────────────────────────────────┘
```

### 1.3 Real-Time Conversation Loop

Inside `SessionOrchestrator`, every turn follows this cycle:

```
Deepgram STT                Session Orchestrator              GPT-4o + TTS
    │                              │                              │
    │  on_transcript(text,         │                              │
    │    confidence, is_final)     │                              │
    │ ────────────────────────────>│                              │
    │                              │                              │
    │              ┌───────────────┤                              │
    │              │ INTERIM:      │                              │
    │              │ • Dedup check │                              │
    │              │ • Feed turn   │                              │
    │              │   detector    │                              │
    │              │ • If agent    │                              │
    │              │   speaking +  │                              │
    │              │   substantive │                              │
    │              │   → interrupt │                              │
    │              │   TTS         │                              │
    │              └───────────────┤                              │
    │                              │                              │
    │              ┌───────────────┤                              │
    │              │ FINAL:        │                              │
    │              │ 1. Dedup      │                              │
    │              │ 2. Confidence │                              │
    │              │    filter     │                              │
    │              │    (>0.6)     │                              │
    │              │ 3. Barge-in   │                              │
    │              │    handling   │                              │
    │              │ 4. Compliance │                              │
    │              │    scan       │                              │
    │              │ 5. Refusal    │                              │
    │              │    detection  │                              │
    │              │ 6. Turn       │                              │
    │              │    completion │                              │
    │              │    check      │                              │
    │              │ 7. Fire LLM   │                              │
    │              └───────────────┼─────────────────────────────>│
    │                              │  generate_and_speak()        │
    │                              │                              │
    │                              │  ┌─ PARALLEL ─────────────┐  │
    │                              │  │ Fast model (mini):     │  │
    │                              │  │  first sentence only   │  │
    │                              │  │  ~100-200ms TTFT       │  │
    │                              │  │                        │  │
    │                              │  │ Main model (GPT-4o):   │  │
    │                              │  │  full response stream  │  │
    │                              │  │  ~400-600ms TTFT       │  │
    │                              │  └────────────────────────┘  │
    │                              │                              │
    │                              │  sentence_queue ◄── sentences│
    │                              │       │                      │
    │                              │       ▼                      │
    │                              │  _stream_tts_from_queue()    │
    │                              │  ├─ Wait for yield phrase    │
    │                              │  │  to finish (if barge-in)  │
    │                              │  ├─ FDCPA guard check        │
    │                              │  ├─ ElevenLabs TTS stream    │
    │                              │  ├─ Mulaw encode             │
    │                              │  └─ Send to Twilio           │
    │                              │       │                      │
    │                              │       ▼                      │
    │                              │  Borrower hears response     │
```

### 1.4 Call State Machine

```
greeting ──────> mini_miranda ──────> negotiating ──────> closing ──────> ended
   │                  │                    │                  │             │
   │ Agent says       │ FDCPA required     │ Main negotiation │ Wrapping   │ Call
   │ "Hi, is {name}   │ disclosure.        │ loop. Refusal    │ up. Final  │ ended.
   │  available?"     │ Cannot be          │ detection +      │ promises   │ Post-call
   │                  │ interrupted        │ pressure         │ recorded.  │ analysis
   │                  │ (_interruptible    │ escalation       │            │ triggered.
   │                  │  = False)          │ (levels 1-4).    │            │
```

**State transitions** are driven by the LLM's function calls:
- `end_call(outcome)` → `ended`
- `record_promise(amount, date)` → stays in `negotiating` or `closing`
- `trigger_opt_out(reason)` → `ended` (borrower opted out)
- `log_dispute(reason)` → `ended` (debt disputed, collection paused)
- `escalate_to_human()` → `ended` (transfer to human agent)
- `request_callback(time)` → `ended` (callback scheduled)

---

## 2. Barge-In / Interruption System

The system detects borrower interruptions through two parallel paths:

### Path A: Audio-Level (sub-100ms)

```
Twilio media frame (20ms)
    │
    ▼
mulaw → PCM 16-bit
    │
    ▼
BargeInDetector.detect(pcm)
    │
    ├─ AEC: subtract estimated echo (spectral subtraction)
    ├─ Silero VAD: neural speech probability (torchaudio resample 8k→16k)
    │   └─ Smoothed via EMA (alpha=0.35)
    ├─ Energy gate: smoothed prob > 0.5 AND energy > adaptive threshold
    ├─ Consecutive frame check: 2+ frames required
    ├─ Cooldown: 400ms since last barge-in
    └─ Min speaking: agent speaking for 120ms+
         │
         ▼ (if all pass)
    _interrupt_tts()
    ├─ Cancel LLM + TTS tasks
    ├─ Mark agent not speaking
    ├─ Clear Twilio audio buffer
    └─ Increment speech_id (kills in-flight chunks)
```

### Path B: Transcript-Level (200-500ms)

```
Deepgram interim transcript
    │
    ▼
Substantive check:
├─ Not backchannel ("uh-huh", "okay")
├─ ≥3 words + verb/question word, OR ≥5 words
├─ Agent is speaking
└─ 400ms cooldown passed
    │
    ▼ (if all pass)
_interrupt_tts() + _barge_in_pending = True
```

### Response Pipeline

```
Deepgram final transcript
    │
    ▼
Intent classification:
├─ Question → "answer directly"
├─ Objection → "respond with persuasion"
└─ Clarification → "respond briefly"
    │
    ├─ Build barge_in_note with context
    ├─ Check payment intent → de-escalate
    ├─ Fire _generate_and_speak()
    └─ Play yield phrase ("Sure", "Haan", "Heli")
```

### Instrumentation

14 Prometheus metrics track barge-in performance:
- `barge_in_triggered_total{path}` — audio vs transcript triggers
- `barge_in_interrupt_latency_ms` — detection-to-clear time
- `vad_speech_probability` — Silero output distribution
- `aec_echo_gain` — echo attenuation levels
- `fast_first_sentence_ttft_ms` — fast model latency

---

## 3. FDCPA Compliance — Three Layers

### Layer 1: Pre-Call Gate (app/services/compliance/fdcpa_guard.py)

Runs BEFORE Twilio dial. Blocks the call if:
- Borrower is on DNC list (Redis hash)
- Borrower has opted out (`opted_out = True`)
- Borrower filed bankruptcy or is deceased
- TCPA consent not recorded
- Outside call window (8AM-9PM borrower local time)
- Call frequency exceeded (1/day, 3/week, 12/month per FDCPA)

### Layer 2: Agent Output Filter (real-time)

Every sentence from GPT-4o is checked BEFORE TTS dispatch:
```python
guard = check_agent_response(sentence)
if guard.blocked:
    skip this sentence  # never reaches borrower
```

Regex patterns block:
- Threats of arrest/jail/prosecution
- Direct lawsuit threats
- Abusive language
- Harassment or violence
- Third-party disclosure threats
- False urgency (police/sheriff threats)

### Layer 3: Borrower Speech Scanner (real-time)

Every borrower transcript is scanned for:
- **Opt-out triggers** (21 patterns): "stop calling", "cease and desist", "my lawyer", "CFPB"
  → Auto opt-out: set flags, cancel pending calls, add to Redis DNC, log compliance event
- **Dispute triggers** (7 patterns): "not my debt", "identity theft", "validate the debt"
  → Log dispute event, pause collection activity

### Mini-Miranda Protection

The FDCPA-required disclosure at call start is marked `_interruptible = False`. The borrower cannot interrupt this — it plays to completion regardless of barge-in detection. This is a legal requirement.

---

## 4. ML Strategy Selection

```
Borrower profile
    │
    ▼
StrategyEngine.predict(borrower)
    │
    ├─ If model loaded + confidence ≥ 0.45:
    │   └─ XGBoost classifier (300 estimators, max_depth=6)
    │       Features: DPD, log_balance, debt_type, hour, day_of_week,
    │                 prev_attempts, avg_sentiment, avoidance, engagement,
    │                 promise_kept_rate
    │       Output: reminder | negotiation | settlement | escalation | skip
    │
    └─ If cold-start or low confidence:
        └─ Rule-based fallback:
            ├─ DPD 0-30   → reminder
            ├─ DPD 30-90  → negotiation
            ├─ DPD 90+    → settlement
            └─ High avoidance → escalation

    Compliance override: skip if opted_out, DNC, or bankruptcy
```

**Retraining**: Weekly via Celery beat (Sunday 3AM UTC). Trains on `ml_call_outcomes` table. Requires ≥100 rows. Validates on 20% holdout. Only promotes if ROC-AUC improves.

---

## 5. Turn Detection System

```
Deepgram final transcript
    │
    ▼
TurnDetector.analyze(transcript, confidence)
    │
    ├─ DEFINITE COMPLETE:
    │   ├─ Questions (ends with ? + question word)
    │   ├─ Explicit signals ("that's it", "bas itna")
    │   └─ Short definitive ("no", "yes", "sure")
    │
    ├─ DEFINITE INCOMPLETE:
    │   ├─ Trailing conjunction ("but", "and", "lekin", "aur")
    │   ├─ Trailing preposition ("to", "for", "ke liye")
    │   └─ Incomplete verb phrase ("I was going to", "karna chahta")
    │
    └─ HEURISTIC (0.0-1.0 score):
        ├─ +0.25 sentence-ending punctuation
        ├─ +0.15 subject + verb structure detected
        ├─ -0.20 enumeration pattern ("first...", "one thing...")
        ├─ +0.10 long utterance (≥10 words)
        ├─ +0.05 high STT confidence (>0.92)
        ├─ -0.15 high speech velocity (>3 words/sec from interims)
        └─ Complete if score ≥ 0.55

    If incomplete + confidence > 0.7 → WAIT for next transcript
    If complete → fire LLM
```

---

## 6. Fast First Sentence Architecture

```
borrower_text arrives
         │
         ▼
┌─ PARALLEL RACE ──────────────────────────────────┐
│                                                    │
│  ┌─ gpt-4o-mini (fast) ─┐  ┌─ gpt-4o (main) ──┐ │
│  │ max_tokens=60         │  │ max_tokens=150    │ │
│  │ "Generate ONLY first  │  │ Full response     │ │
│  │  sentence"            │  │ with function     │ │
│  │ ~100-200ms TTFT       │  │ calling           │ │
│  └──────────┬────────────┘  │ ~400-600ms TTFT   │ │
│             │               └─────────┬─────────┘ │
│             ▼                         │            │
│    sentence_queue.put()               │            │
│    (if main hasn't sent yet)          │            │
│             │                         │            │
│             ▼                         ▼            │
│        TTS plays fast sentence   Main continues    │
│        immediately               streaming rest    │
└────────────────────────────────────────────────────┘

SKIP fast path when compliance-sensitive:
├─ Question turns (need precise data)
├─ Pressure turns (FDCPA constraints)
├─ Payment intent turns (de-escalation phrasing)
└─ Barge-in turns (context-aware response needed)
```

---

## 7. Post-Call Analysis Pipeline

```
Call ends (WebSocket "stop" or function call end_call)
         │
         ▼
Celery task: post_call_analysis(call_sid, outcome)
         │
         ├─ 1. Persist Redis conversation to PostgreSQL
         │     ├─ Create ConversationTurn rows (per turn)
         │     └─ Update Call record (duration, outcome, latencies)
         │
         ├─ 2. AI Intelligence Report (GPT-4o analysis)
         │     ├─ Feed full transcript to analyzer
         │     ├─ Extract: sentiment, willingness_to_pay, payment_intent_score
         │     ├─ Extract: key_objections, promising_signals
         │     ├─ Generate: recommended_strategy, summary, turning_points
         │     ├─ Estimate: repayment_probability + reasoning
         │     └─ Store in CallAnalysis table
         │
         ├─ 3. Update borrower behavioral scores
         │     ├─ engagement_score (0-1)
         │     ├─ repayment_likelihood (0-1)
         │     ├─ avoidance_score (0-1)
         │     ├─ sentiment_trend
         │     └─ promise_kept_rate
         │
         ├─ 4. Record ML training outcome
         │     └─ MLCallOutcome (features + outcome + success flag)
         │
         ├─ 5. Build follow-up brief
         │     ├─ AI summary of conversation
         │     ├─ Key points for next call
         │     ├─ Suggested personalized opening
         │     └─ Stored for next call's system prompt
         │
         └─ 6. Schedule retry (if applicable)
               └─ Create CallSchedule entry for next attempt
```

---

## 8. Multi-Tenancy Architecture

```
Request arrives
    │
    ▼
JWT / API Key extraction (app/dependencies.py)
    │
    ├─ JWT: decode → extract org_id from claims
    │        verify user.is_active
    │        set tenant context
    │
    └─ API Key: hash → lookup in api_keys table
                 verify not expired
                 set tenant context from key's org_id
    │
    ▼
Every database query scoped:
    SELECT * FROM borrowers WHERE organization_id = :org_id

Role hierarchy:
    owner > admin > manager > agent > readonly

Tables with organization_id:
    borrowers, calls, campaigns, call_analyses,
    compliance_events, human_calls, call_schedule,
    webhooks, audit_log, subscriptions, usage_records, invoices
```

---

## 9. Billing & Usage Metering

```
Call placed
    │
    ▼
Redis INCRBY org:{id}:{date}:ai_minutes  ← real-time, <1ms
Redis INCRBY org:{id}:{date}:ai_calls
    │
    ├─ Every 5 min (Celery beat):
    │   └─ Flush to PostgreSQL usage_records
    │
    ├─ End of billing period:
    │   └─ Sync to Stripe Usage Records → invoice
    │
    └─ Pre-call admission check:
        ├─ Subscription active? (not cancelled/past_due)
        ├─ Usage within plan limits?
        └─ Reject 402 if exceeded

Plan tiers:
    Starter  $499/mo  │ 500 AI min │ 1K borrowers │ 2 users
    Growth  $1999/mo  │ 5K AI min  │ 25K borrowers│ 10 users
    Enterprise Custom │ Unlimited  │ Unlimited    │ Unlimited
```

---

## 10. Webhook Event System

```
Event occurs (call.completed, payment.promised, etc.)
    │
    ▼
dispatch_event(db, org_id, event_type, payload)
    │
    ├─ Find all active webhooks for org subscribing to event
    │
    └─ For each webhook:
        ├─ Build payload JSON
        ├─ Compute HMAC-SHA256 signature
        │   Header: X-DebtCollector-Signature: sha256={sig}
        ├─ POST to webhook URL (10s timeout)
        ├─ Record WebhookDelivery (status, duration, response)
        ├─ On success: reset failure_count
        └─ On failure: increment failure_count
            └─ After 10 failures: auto-disable webhook
```

---

## 11. Database Schema

### Core Tables

```
organizations        users              api_keys          invitations
├─ id (PK)           ├─ id (PK)         ├─ id (PK)        ├─ id (PK)
├─ name              ├─ organization_id  ├─ organization_id ├─ organization_id
├─ slug (unique)     ├─ email (unique)   ├─ key_hash       ├─ email
├─ plan_tier         ├─ password_hash    ├─ key_prefix     ├─ role
├─ status            ├─ role             ├─ name           ├─ token_hash
├─ agent_name        ├─ is_active        ├─ scopes (JSONB) ├─ expires_at
├─ agency_name       ├─ mfa_enabled      ├─ expires_at     └─ accepted_at
└─ settings (JSONB)  └─ last_login_at    └─ is_active

borrowers            calls                    campaigns
├─ id (PK)           ├─ id (PK)               ├─ id (PK)
├─ organization_id   ├─ organization_id        ├─ organization_id
├─ external_id       ├─ twilio_call_sid        ├─ name
├─ phone_e164 (enc)  ├─ borrower_id (FK)       ├─ strategy_type
├─ phone_hash        ├─ campaign_id (FK)       ├─ status (draft/active)
├─ principal_amount  ├─ status                 ├─ max_attempts
├─ current_balance   ├─ outcome                ├─ call_window_start/end
├─ days_past_due     ├─ promise_amount/date    ├─ retry_interval_hrs
├─ debt_type         ├─ payment_collected      └─ settlement_floor_pct
├─ do_not_call       ├─ sentiment_initial/final
├─ opted_out         ├─ llm/tts/stt_latency_avg_ms
├─ engagement_score  ├─ fdcpa_violations (JSONB)
├─ repayment_likelih ├─ turn_count
└─ avoidance_score   └─ interruption_count

conversation_turns        call_analyses            compliance_events
├─ id (PK)                ├─ id (PK)               ├─ id (PK)
├─ call_id (FK)           ├─ organization_id        ├─ organization_id
├─ turn_index             ├─ ai_call_id (FK)        ├─ borrower_id (FK)
├─ speaker (agent/borr)   ├─ human_call_id (FK)     ├─ call_id (FK)
├─ raw_transcript         ├─ borrower_id (FK)       ├─ event_type
├─ stt_confidence         ├─ overall_sentiment      ├─ severity
├─ sentiment_score        ├─ willingness_to_pay     ├─ description
├─ intent                 ├─ repayment_probability  └─ auto_actioned
├─ entities (JSONB)       ├─ key_objections
├─ barge_in (bool)        ├─ recommended_strategy
├─ llm_latency_ms         └─ summary
└─ tts_latency_ms

subscriptions          usage_records          plan_limits
├─ id (PK)             ├─ id (PK)             ├─ id (PK)
├─ organization_id     ├─ organization_id      ├─ tier (unique)
├─ stripe_customer_id  ├─ period_start (date)  ├─ monthly_ai_minutes
├─ plan_tier           ├─ ai_call_minutes      ├─ max_borrowers
├─ status              ├─ ai_calls_count       ├─ max_users
├─ trial_ends_at       ├─ successful_collect.   ├─ per_minute_rate_cents
└─ current_period_end  └─ api_calls_count      └─ base_price_cents

webhooks              webhook_deliveries     audit_log
├─ id (PK)            ├─ id (PK)             ├─ id (PK)
├─ organization_id    ├─ webhook_id (FK)      ├─ organization_id
├─ url                ├─ event_type           ├─ user_id (FK)
├─ secret (HMAC)      ├─ payload (JSONB)      ├─ action
├─ events (JSONB)     ├─ status_code          ├─ resource_type
├─ failure_count      ├─ success              ├─ resource_id
└─ is_active          └─ duration_ms          ├─ changes (JSONB)
                                               └─ ip_address
```

---

## 12. Redis Session State

During a live call, all state lives in Redis (TTL 4 hours):

```
session:{call_sid}
├─ state: "greeting" | "mini_miranda" | "negotiating" | "closing" | "ended"
├─ agent_speaking: "true" | "false"
├─ mini_miranda_delivered: "true" | "false"
├─ refusal_count: "0" | "1" | "2" | ...
├─ turn_count: "12"
├─ current_offer: "500.00"
├─ entities_extracted: {amounts, dates, names}
├─ compliance_flags: {opt_out_requested, dispute_filed}
└─ last_activity_at: ISO timestamp

session:{call_sid}:history (list, capped at 30 turns)
├─ {"role": "agent", "content": "Hi, is John available?"}
├─ {"role": "borrower", "content": "Yeah, this is John"}
└─ ...

session:{call_sid}:speaking_guard (TTL 10s)
└─ "1"  ← expires if process crashes, auto-resets agent_speaking
```

---

## 13. Frontend Architecture

```
React 19 + TypeScript + Vite + TailwindCSS 4

Routes (protected by AuthContext):
/                     Dashboard (KPIs, hourly breakdown, outcome distribution)
/borrowers            Borrower list with search/filter
/borrowers/:id        Borrower detail + intelligence history
/calls                Call list
/calls/:id            Call detail (transcript, sentiment chart, follow-up brief)
/campaigns            Campaign grid
/campaigns/:id        Campaign detail + borrower management
/compliance           Compliance audit trail (7-year retention)
/call-quality         Latency metrics (STT/LLM/TTS, p95, barge-in rate)
/human-calls          Human agent browser-based calling (Twilio Client SDK)
/human-calls/:id      Human call detail + AI analysis
/settings/team        User management (invite, roles, deactivate)
/settings/api-keys    API key CRUD
/settings/billing     Usage dashboard + plan comparison + Stripe integration
/onboarding           6-step setup wizard

Auth routes (public):
/login                Email/password login
/register             Create org + first user (14-day trial)

API client (frontend/src/api/client.ts):
├─ Axios with JWT Bearer token
├─ Automatic token refresh on 401
├─ Request queuing during refresh
└─ Redirect to /login on auth failure
```

---

## 14. Background Workers (Celery)

```
Celery Beat Schedule:
├─ Every 60s:  dispatch_campaign_calls()     [queue: realtime]
│              └─ Find pending CallSchedule entries
│              └─ Place outbound calls for each
│
├─ Every 5m:   flush_usage_to_postgres()     [queue: batch]
│              └─ Sync Redis usage counters to usage_records
│
├─ Daily 2AM:  refresh_all_borrower_scores() [queue: batch]
│              └─ Recalculate engagement, avoidance, repayment likelihood
│
└─ Sunday 3AM: retrain_strategy_model()      [queue: batch]
               └─ Train XGBoost on ml_call_outcomes
               └─ Validate on 20% holdout
               └─ Promote only if ROC-AUC improves

Post-Call Tasks (triggered per call):
├─ post_call_analysis()   [queue: realtime]
│  └─ Persist conversation, run AI analysis, update scores
│
└─ place_outbound_call()  [queue: realtime, max_retries=2]
   └─ Wrapper for call_controller.initiate_outbound_call
```

---

## 15. Monitoring & Observability

```
Prometheus Metrics (GET /metrics):
├─ Call metrics:      calls_initiated/connected/completed_total
├─ Compliance:        compliance_violations_total{type}
├─ Latency:           stt/llm/tts/e2e_latency_ms (histograms)
├─ Barge-in:          barge_in_triggered_total{path}
│                     barge_in_interrupt_latency_ms
├─ VAD:               vad_speech_probability (histogram)
│                     vad_backend_used_total{backend}
├─ AEC:               aec_echo_detected_total
│                     aec_echo_gain (histogram)
├─ Turn detection:    turn_detection_decisions_total{decision,reason}
├─ Fast-first:        fast_first_sentence_wins_total
│                     fast_first_sentence_ttft_ms
│                     fast_first_sentence_skipped_total{reason}
└─ Infrastructure:    active_calls (gauge)

Health Checks:
├─ GET /health/live   → always 200 (liveness)
└─ GET /health/ready  → checks PostgreSQL + Redis (readiness)

OpenTelemetry:
└─ Tracing via OTLP exporter to collector
```

---

## 16. Security Architecture

```
Authentication:
├─ JWT (HS256, 15min access, 7-day refresh)
├─ API Key auth (SHA-256 hashed, X-API-Key header)
├─ Password hashing: bcrypt via passlib
└─ Rate limiting: Redis sliding window
    ├─ Auth endpoints: 10 req/min
    ├─ Authenticated: 1000 req/min
    └─ Unauthenticated: 100 req/min

PII Protection:
├─ Phone numbers: Fernet encryption at rest
├─ Phone lookup: SHA-256 hash for deduplication
├─ Email: SHA-256 hash
└─ Encryption key: PII_ENCRYPTION_KEY env var

Tenant Isolation:
├─ organization_id on all tables
├─ All queries scoped by org_id from JWT claims
├─ Composite indexes: (organization_id, created_at)
└─ API key scoped to creating org
```

---

## 17. Infrastructure (Docker Compose)

```yaml
Services:
├─ postgres:16-alpine     Port 5433, healthcheck, persistent volume
├─ redis:7-alpine         Port 6379, AOF enabled, persistent volume
├─ api                    Port 8000, depends on postgres+redis, reload in dev
├─ worker                 Celery worker, 4 concurrency, queues: realtime+batch
├─ beat                   Celery Beat scheduler
└─ flower                 Port 5555, Celery monitoring UI
```

---

## 18. Key Latency Budget

```
Target: <600ms per response turn (borrower speaks → borrower hears response)

Budget breakdown:
├─ Deepgram STT:        50-150ms  (interim faster, final ~150ms)
├─ Barge-in detection:  20-60ms   (audio-level path)
├─ Turn detection:      <1ms      (rule-based, synchronous)
├─ LLM (fast path):     100-200ms (gpt-4o-mini first sentence)
├─ LLM (main path):     400-600ms (gpt-4o full response)
├─ FDCPA guard:         <1ms      (regex, synchronous)
├─ ElevenLabs TTS:      80-200ms  (turbo v2, first chunk)
├─ Network overhead:    50-100ms  (Twilio ↔ server round-trip)
└─ Total (fast path):   ~300-500ms
   Total (main path):   ~600-1000ms
```

---

## 19. Supported Languages

| Language | Greeting | Yield Phrases | Refusal Detection | Mini-Miranda |
|----------|----------|---------------|-------------------|--------------|
| English  | Yes      | Sure, Go ahead, I hear you | Yes (full regex) | Yes |
| Hindi    | Yes      | Haan, Boliye, Ji zaroor | Yes (Devanagari) | Yes |
| Kannada  | Yes      | Heli, Heege, Haan | Yes (Kannada script) | Yes |
| Telugu   | Yes      | Cheppandi, Antara, Haan | Yes (Telugu script) | Yes |

---

## 20. File Map

```
app/
├── main.py                              App factory, middleware, SPA mount
├── config.py                            Pydantic Settings (all env vars)
├── dependencies.py                      FastAPI deps (DB, Redis, auth, tenant)
│
├── api/
│   ├── v1/
│   │   ├── router.py                    Central router (16 sub-routers)
│   │   ├── auth.py                      Register, login, refresh, me
│   │   ├── users.py                     Invite, CRUD, roles
│   │   ├── organizations.py             Org settings, API keys
│   │   ├── billing.py                   Subscription, usage, Stripe webhooks
│   │   ├── calls.py                     Call initiation, detail, transcript
│   │   ├── borrowers.py                 Borrower CRUD, intelligence, opt-out
│   │   ├── campaigns.py                 Campaign CRUD, borrower assignment
│   │   ├── analytics.py                 Dashboard KPIs, call quality
│   │   ├── compliance.py                Consent, compliance events
│   │   ├── human_calls.py               Browser-based calling, Twilio tokens
│   │   ├── webhooks.py                  Webhook CRUD, test, deliveries
│   │   ├── audit.py                     Immutable audit log
│   │   ├── onboarding.py                Setup wizard, CSV upload, voice test
│   │   ├── marketplace.py               Template browse, install, publish
│   │   └── telephony.py                 TwiML, voice client, status callbacks
│   └── websocket/
│       └── media_stream.py              Twilio WebSocket audio handler
│
├── core/
│   ├── session_orchestrator.py          Call state machine (990 lines)
│   ├── conversation_manager.py          Turn-by-turn dialogue (Redis-backed)
│   ├── barge_in_detector.py             Silero VAD + AEC + adaptive threshold
│   ├── turn_detector.py                 Semantic turn-completion analysis
│   ├── auth.py                          JWT creation/validation, password hashing
│   ├── tenant.py                        Multi-tenancy context
│   ├── permissions.py                   RBAC (owner/admin/manager/agent/readonly)
│   ├── rate_limiter.py                  Redis sliding window
│   └── audit.py                         Audit log helpers
│
├── services/
│   ├── llm/
│   │   ├── gpt4o_client.py              Streaming GPT-4o + fast-first-sentence
│   │   ├── prompt_builder.py            System prompt construction
│   │   └── function_registry.py         LLM function call schemas
│   ├── stt/
│   │   └── deepgram_client.py           Deepgram nova-2 streaming WebSocket
│   ├── tts/
│   │   └── elevenlabs_client.py         ElevenLabs turbo v2 streaming
│   ├── compliance/
│   │   ├── fdcpa_guard.py               3-layer FDCPA enforcement
│   │   ├── opt_out_handler.py           Process opt-outs
│   │   └── consent_manager.py           TCPA consent recording
│   ├── ml/
│   │   ├── strategy_engine.py           XGBoost strategy prediction
│   │   ├── feature_extractor.py         Borrower → feature vector
│   │   └── outcome_tracker.py           Record ML training data
│   ├── profiling/
│   │   ├── sentiment_analyzer.py        Per-turn sentiment scoring
│   │   ├── borrower_scorer.py           Behavioral score updates
│   │   └── behavioral_tracker.py        Event logging
│   ├── memory/
│   │   ├── redis_session.py             Call session state in Redis
│   │   └── vector_store.py              FAISS semantic context retrieval
│   ├── telephony/
│   │   ├── call_controller.py           Outbound call orchestration
│   │   └── twilio_client.py             Twilio API wrapper
│   ├── billing/
│   │   ├── stripe_service.py            Stripe integration
│   │   ├── usage_meter.py               Redis usage counters + flush
│   │   └── plan_enforcer.py             Call admission control
│   ├── webhooks/
│   │   └── dispatcher.py                HMAC-signed webhook delivery
│   ├── follow_up/
│   │   ├── follow_up_brief.py           AI-generated follow-up context
│   │   └── followup.py                  Follow-up call logic
│   ├── reports/
│   │   └── (scheduled report generation)
│   └── scheduling/
│       ├── call_scheduler.py            Call retry scheduling
│       └── campaign_runner.py           Campaign dispatch (Celery beat)
│
├── models/
│   └── database/
│       ├── base.py                      SQLAlchemy engine + Base
│       ├── organization.py              Organization model
│       ├── user.py                      User, APIKey, Invitation
│       ├── borrower.py                  Borrower (PII encrypted)
│       ├── call.py                      AI call records
│       ├── human_call.py                Human agent call records
│       ├── call_analysis.py             AI intelligence reports
│       ├── campaign.py                  Campaign + CampaignBorrower + CallSchedule
│       ├── compliance.py                Compliance events
│       ├── conversation.py              ConversationTurn, BehavioralEvent, RepaymentPromise
│       ├── billing.py                   Subscription, UsageRecord, PlanLimit, Invoice
│       ├── webhook.py                   Webhook, WebhookDelivery, AuditLog, ScheduledReport
│       ├── onboarding.py                OnboardingProgress, MarketplaceTemplate
│       └── ml_outcome.py               ML training data
│
├── workers/
│   ├── celery_app.py                    Celery config + beat schedule
│   └── tasks/
│       ├── call_tasks.py                place_outbound_call, dispatch_campaign_calls
│       ├── analytics_tasks.py           post_call_analysis, refresh_borrower_scores
│       ├── ml_tasks.py                  retrain_strategy_model
│       └── notification_tasks.py        (placeholder: Slack/email/PagerDuty)
│
├── monitoring/
│   ├── metrics.py                       Prometheus metrics (30+ metrics)
│   └── health.py                        Liveness + readiness probes
│
└── utils/
    ├── audio_utils.py                   mulaw/PCM conversion, RMS, ZCR
    └── crypto.py                        Fernet encrypt/decrypt, SHA-256 hash

frontend/
├── src/
│   ├── App.tsx                          Routes + AuthProvider
│   ├── api/client.ts                    Axios + JWT interceptor
│   ├── contexts/AuthContext.tsx          Auth state management
│   ├── components/layout/
│   │   ├── AppShell.tsx                 Main layout wrapper
│   │   └── Sidebar.tsx                  Navigation (6 sections)
│   └── pages/
│       ├── Auth/Login.tsx               Login form
│       ├── Auth/Register.tsx            Registration + org creation
│       ├── Dashboard.tsx                KPI dashboard
│       ├── Borrowers/                   List + detail views
│       ├── Calls/                       List + detail (transcript, sentiment)
│       ├── Campaigns/                   List + detail + management
│       ├── Compliance.tsx               Audit trail
│       ├── CallQuality.tsx              Latency metrics
│       ├── HumanCalls/                  Browser-based calling
│       ├── Settings/Team.tsx            User management
│       ├── Settings/ApiKeys.tsx         API key management
│       ├── Billing/Usage.tsx            Usage + plans + Stripe
│       └── Onboarding/OnboardingWizard  6-step setup wizard

migrations/
├── versions/
│   ├── 0001_initial_schema.py           Core tables
│   ├── 0002_call_intelligence.py        CallAnalysis model
│   ├── 0003_separate_human_calls.py     HumanCall table
│   ├── 0004_human_calls_contact_fields  Contact info columns
│   ├── 0005_ai_call_analysis.py         ai_call_id FK
│   ├── 0006_multi_tenancy.py            organizations + users + org_id on all tables
│   ├── 0007_billing.py                  subscriptions + usage + plans + invoices
│   └── 0008_enterprise_features.py      webhooks + audit + reports + onboarding + marketplace
```
