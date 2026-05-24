# DebtCollector — Claude Code Guide

## Project Overview

Production-grade AI voice agent for debt collection. Orchestrates real-time phone calls using Twilio, with Deepgram STT → GPT-4o LLM → ElevenLabs TTS pipeline, FDCPA compliance enforcement, and ML-driven strategy selection.

## Architecture

```
Frontend (React + TypeScript + Vite)
    ↓ REST
Backend (FastAPI, async)
    ├── REST API        app/api/v1/
    ├── WebSocket       app/api/websocket/media_stream.py   ← Twilio audio stream
    ├── Core            app/core/session_orchestrator.py    ← call state machine
    ├── Services        app/services/                       ← LLM, STT, TTS, compliance
    ├── Workers         app/workers/                        ← Celery tasks
    └── Models          app/models/                         ← SQLAlchemy ORM + Pydantic schemas

Infrastructure: PostgreSQL 16, Redis 7, Celery (broker + beat)
ML: XGBoost strategy model, FAISS vector store
```

## Real-Time Call Pipeline

1. `POST /api/v1/calls/initiate` → enqueue Celery task
2. Twilio dials borrower → WebSocket `/media_stream` receives audio frames
3. Deepgram transcribes → GPT-4o streams response → sentence-boundary dispatch to ElevenLabs
4. ElevenLabs returns mu-law audio → Twilio streams back to borrower
5. Every LLM output checked by `app/services/compliance/fdcpa_guard.py`
6. Outcomes (promises, opt-outs, disputes) recorded via function calls

**Target latency**: <600ms per response turn

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app factory |
| `app/config.py` | Pydantic Settings (all env vars) |
| `app/core/session_orchestrator.py` | Live call state machine |
| `app/core/conversation_manager.py` | Turn-by-turn dialogue |
| `app/api/websocket/media_stream.py` | Twilio WebSocket handler |
| `app/services/llm/gpt4o_client.py` | OpenAI streaming + function calling |
| `app/services/stt/deepgram_client.py` | Deepgram nova-2 STT |
| `app/services/tts/elevenlabs_client.py` | ElevenLabs TTS |
| `app/services/compliance/fdcpa_guard.py` | 3-layer FDCPA enforcement |
| `app/services/ml/strategy_engine.py` | XGBoost strategy selection |
| `app/workers/celery_app.py` | Celery config + beat schedule |
| `app/models/database/` | SQLAlchemy ORM models |
| `frontend/src/` | React SPA |
| `ml/training/train_strategy_model.py` | Offline retraining script |
| `migrations/` | Alembic schema migrations |

## Getting Started

### Docker (recommended)
```bash
cp .env.example .env          # fill in API keys
docker-compose up
docker-compose exec api alembic upgrade head
docker-compose exec api python scripts/seed_borrowers.py --count 20
python test_apis.py           # smoke test
```

**Services**: API :8000, PostgreSQL :5433, Redis :6379, Flower :5555

### Local Development
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --loglevel=info -Q realtime,batch
celery -A app.workers.celery_app beat --loglevel=info
cd frontend && npm install && npm run dev   # :5173
```

### Tests
```bash
pytest tests/unit/ -v --asyncio-mode=auto
python test_apis.py   # requires running API
```

### Frontend Build
```bash
cd frontend && npm run build
cp -r dist/* ../static/
```

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Twilio credentials |
| `TWILIO_FROM_NUMBER` | Outbound caller ID (e.g. `+12138387179`) |
| `TWILIO_WEBHOOK_BASE_URL` | Public HTTPS URL for Twilio callbacks |
| `OPENAI_API_KEY` | GPT-4o access |
| `DEEPGRAM_API_KEY` | STT |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | TTS |
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `PII_ENCRYPTION_KEY` | Base64 Fernet key (for phone/PII encryption) |
| `APP_SECRET_KEY` | 32+ char secret |

Full reference: `.env.example` → `app/config.py`

## FDCPA Compliance (Critical)

Three enforcement layers in `app/services/compliance/`:

1. **Pre-call** (`fdcpa_guard.py`): DNC check, opt-out check, call frequency limits (1/day, 3/week, 12/month), call window 8 AM–9 PM borrower local time
2. **Agent output**: Regex blocks threats, harassment, false urgency, non-disclosure
3. **Borrower speech**: Detects "cease and desist", "attorney", "sue" → auto opt-out + call stop

Do not modify compliance logic without understanding FDCPA requirements.

## Database Migrations

```bash
alembic revision --autogenerate -m "description"   # create
alembic upgrade head                                 # apply
alembic downgrade -1                                 # rollback
```

## Celery Scheduled Tasks

| Task | Schedule |
|------|---------|
| Campaign call dispatch | Every 60s |
| Borrower score refresh | Daily 2 AM UTC |
| ML strategy model retrain | Sunday 3 AM UTC |
| Notifications | Batch queue |

## Tech Stack

**Backend**: Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Celery, Redis, PostgreSQL
**AI/Voice**: OpenAI GPT-4o, Deepgram nova-2, ElevenLabs turbo v2, Twilio
**ML**: XGBoost, scikit-learn, FAISS, NumPy
**Frontend**: React 19, TypeScript, Vite, TailwindCSS 4, React Query, Zod
**Observability**: Prometheus, OpenTelemetry
