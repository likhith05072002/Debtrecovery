# DebtCollector Project Report

## 1. Project Summary

`debtcollector` is an AI-assisted debt collection platform with:

- a FastAPI backend for APIs, websocket media streams, compliance checks, campaign management, borrower management, analytics, and call orchestration
- a React + Vite frontend for the operator dashboard and workflow screens
- Redis for realtime session state and Celery queues
- PostgreSQL for persistent borrower, call, campaign, and analysis data
- external integrations for Twilio telephony, Deepgram speech-to-text, OpenAI LLM reasoning, and ElevenLabs text-to-speech
- ML and profiling layers for strategy selection, repayment prediction, borrower behavior analysis, and post-call intelligence

At a high level, the product manages borrowers and campaigns, places AI or human-assisted calls, streams call audio through websocket endpoints, generates agent responses in real time, stores conversation turns, and analyzes calls afterward to improve future outreach.

## 2. High-Level Runtime Flow

1. A borrower or campaign action starts a call.
2. Telephony services create and control the call session.
3. Audio is streamed into websocket handlers.
4. Speech is transcribed, compliance is checked, and the orchestrator decides the next response.
5. The LLM prompt builder and client generate a reply.
6. TTS converts the reply into spoken audio.
7. Conversation turns, outcomes, and analysis are saved.
8. The frontend reads that data through REST APIs and presents dashboards, call details, compliance views, and campaign operations.

## 3. Documentation Scope

This report focuses on the maintained code and configuration that define the product.

Detailed coverage includes:

- backend application code in `app/`
- frontend application code in `frontend/src/`
- migrations
- Docker and startup files
- scripts and tests
- ML training entrypoints

Summarized only:

- `venv/`
- `frontend/node_modules/`
- `__pycache__/`
- compiled frontend bundles in `static/assets/`
- log output files

## 4. Top-Level Tree

```text
debtcollector/
├─ .claude/
├─ app/
│  ├─ agents/
│  ├─ api/
│  ├─ core/
│  ├─ models/
│  ├─ monitoring/
│  ├─ services/
│  ├─ utils/
│  └─ workers/
├─ docker/
├─ docs/
├─ frontend/
│  ├─ public/
│  └─ src/
├─ infra/
├─ migrations/
│  └─ versions/
├─ ml/
│  └─ training/
├─ scripts/
├─ static/
├─ tests/
│  └─ unit/
├─ venv/                         generated virtual environment
├─ .env                          local secrets and environment values
├─ .env.example                  sample environment template
├─ .gitignore                    git ignore rules
├─ alembic.ini                   Alembic migration configuration
├─ CLAUDE.md                     repository guidance/instructions file
├─ docker-compose.yml            local multi-service stack
├─ make_call.py                  helper script to trigger a call
├─ pyproject.toml                Python project metadata and tool config
├─ requirements.txt              backend dependencies
├─ server.log                    runtime log output
├─ start.ps1                     local Windows startup script
└─ test_apis.py                  API smoke-test helper
```

## 5. Folder-By-Folder Explanation

### 5.1 `app/`

Main backend application package. It contains the HTTP API, websocket handlers, domain models, orchestrators, integrations, compliance logic, ML strategy logic, memory/state services, and worker tasks.

### 5.2 `docker/`

Container build and reverse-proxy files for packaging the API and worker services.

### 5.3 `docs/`

Project documentation added for maintainability and onboarding.

### 5.4 `frontend/`

React operator dashboard. It contains route pages, reusable UI components, API clients, styling, and static assets.

### 5.5 `infra/`

Present in the repo but currently empty. It likely exists as a placeholder for future infrastructure-as-code or deployment resources.

### 5.6 `migrations/`

Alembic migration environment and schema history for the PostgreSQL database.

### 5.7 `ml/`

Offline or batch ML training code, separate from the runtime backend service layer.

### 5.8 `scripts/`

Operational scripts for seeding data and running campaigns manually.

### 5.9 `static/`

Backend-served static files, including the SPA shell and shared icons/favicon assets.

### 5.10 `tests/`

Pytest test suite with fixtures and focused unit tests for key backend components.

## 6. File Catalog

## 6.1 Root Files

### `.env`

Local environment configuration. This file usually contains secrets and per-machine overrides for database URLs, API keys, Twilio credentials, model settings, and runtime tuning. It should not be committed.

### `.env.example`

Template for the required environment variables. It documents the expected configuration shape for new environments without exposing real secrets.

### `.gitignore`

Lists files and folders that should not be committed, such as secrets, virtual environments, generated assets, and caches.

### `alembic.ini`

Alembic’s main configuration file. It points the migration tool at the migration environment and sets common migration behavior.

### `CLAUDE.md`

Repository-specific guidance file for AI-assisted development workflows. It typically contains instructions, conventions, or notes used by coding agents.

### `docker-compose.yml`

Defines the local development stack: PostgreSQL, Redis, FastAPI API service, Celery worker, Celery beat scheduler, and Flower monitoring UI.

### `make_call.py`

Helper script used to trigger or test outbound calling from the command line. It is useful for manual end-to-end testing without using the frontend.

### `pyproject.toml`

Python project metadata and tool configuration. It defines package discovery plus settings for pytest, Ruff, and mypy.

### `requirements.txt`

Pinned backend dependency list. It shows the project’s core runtime stack: FastAPI, Celery, SQLAlchemy, Twilio, Deepgram, OpenAI, ElevenLabs, FAISS, scikit-learn, monitoring libraries, and utility packages.

### `server.log`

Log output file generated during local runs. This is operational data, not source code.

### `start.ps1`

Windows-oriented startup script for launching the local application stack quickly.

### `test_apis.py`

Standalone API smoke-test or manual verification script. It is useful for quickly checking endpoints outside the main pytest suite.

### `CUserslikhiDesktopcloudflared.exe`

Binary executable stored at the repo root. This appears to be a local utility artifact rather than application source code.

## 6.2 `.claude/`

The directory exists in the repository tree. It usually stores editor or AI-assistant local metadata. Because it is tooling state rather than core product logic, it is not documented file by file here.

## 6.3 `app/`

### `app/__init__.py`

Marks `app` as a Python package.

### `app/config.py`

Central application settings module. It likely reads environment variables, exposes typed configuration, and defines runtime defaults for telephony, AI services, compliance, scheduling, and infrastructure.

### `app/dependencies.py`

Shared FastAPI dependency wiring such as database sessions, auth-like helpers, service lookups, or reusable request-scoped dependencies.

### `app/main.py`

Backend entrypoint. It creates the FastAPI app, configures logging and CORS, includes REST and websocket routers, exposes monitoring endpoints, serves the frontend shell, creates tables in development startup flow, and cleans up resources on shutdown.

## 6.4 `app/agents/`

### `app/agents/__init__.py`

Package marker for backend agent modules.

### `app/agents/call_intelligence/__init__.py`

Package marker for post-call intelligence features.

### `app/agents/call_intelligence/analyzer.py`

Runs post-call AI analysis on transcripts. It likely extracts borrower characterization, willingness to pay, repayment probability, recommended strategy, key points, and next-call talking points.

### `app/agents/call_intelligence/prompt.py`

Prompt template logic for the call intelligence agent. It defines how transcript analysis requests are framed to the LLM.

### `app/agents/call_intelligence/transcriber.py`

Transcription utility for turning recorded calls into text for later analysis. It supports the post-call intelligence pipeline.

## 6.5 `app/api/`

### `app/api/__init__.py`

Package marker for API modules.

### `app/api/v1/__init__.py`

Package marker for versioned API routes.

### `app/api/v1/router.py`

Main API router aggregator for v1 endpoints. It combines route modules into a single versioned API tree.

### `app/api/v1/analytics.py`

Analytics REST endpoints for dashboard metrics, reporting views, and operational summaries.

### `app/api/v1/borrowers.py`

Borrower CRUD and lookup endpoints. This powers borrower list, detail, and form workflows in the frontend.

### `app/api/v1/calls.py`

AI call REST endpoints. It likely exposes call history, detail retrieval, call initiation, and follow-up related data.

### `app/api/v1/campaigns.py`

Campaign management endpoints for creating, updating, and inspecting campaign runs.

### `app/api/v1/compliance.py`

Compliance-facing endpoints for reviewing DNC, opt-out, consent, and policy-related workflow data.

### `app/api/v1/human_calls.py`

Endpoints for the separate human-call workflow, including records and details for manually handled calls.

### `app/api/v1/telephony.py`

Telephony control endpoints for call setup, webhooks, Twilio coordination, or other real-time call lifecycle actions.

### `app/api/websocket/__init__.py`

Package marker for websocket modules.

### `app/api/websocket/media_stream.py`

Primary realtime websocket handler for AI voice calls. It manages inbound/outbound media stream events, session setup, orchestration, turn persistence, and post-call analysis triggers.

### `app/api/websocket/human_stream.py`

Realtime websocket flow for human-call streaming or call monitoring scenarios distinct from the AI media stream pipeline.

## 6.6 `app/core/`

### `app/core/__init__.py`

Package marker for backend orchestration core.

### `app/core/barge_in_detector.py`

Logic that detects when the borrower interrupts the agent while audio is being spoken. This is important for natural conversation control.

### `app/core/conversation_manager.py`

Conversation-state manager that likely tracks turns, intents, timing, and dialog progression during a live session.

### `app/core/session_orchestrator.py`

The heart of the live call experience. It coordinates greeting/disclosure flow, strategy selection, prompt assembly, compliance checks, memory access, LLM responses, and TTS output.

## 6.7 `app/models/`

### `app/models/__init__.py`

Package marker for data models.

### `app/models/database/__init__.py`

Imports all SQLAlchemy ORM models so metadata and relationships are registered together.

### `app/models/database/base.py`

Defines the SQLAlchemy declarative base, async engine, session factory, and common database helpers.

### `app/models/database/borrower.py`

ORM model for borrowers. It stores identity-safe borrower metadata, balances, delinquency signals, compliance flags, and behavioral scores.

### `app/models/database/call.py`

ORM model for AI calls. It captures lifecycle metadata such as start/end times, duration, outcome, and call routing information.

### `app/models/database/call_analysis.py`

ORM model for post-call analysis artifacts including transcript text, sentiment, willingness to pay, key points, recommended strategy, and next-call talking points.

### `app/models/database/campaign.py`

ORM model for outbound campaigns, including scheduling and grouping of borrower outreach.

### `app/models/database/compliance.py`

ORM model(s) related to compliance tracking, such as opt-out records, consent evidence, or compliance audit data.

### `app/models/database/conversation.py`

ORM model for per-turn conversation records. This stores detailed turn-by-turn transcripts and metadata.

### `app/models/database/human_call.py`

ORM model for human-operated call records, separate from AI call records.

### `app/models/database/ml_outcome.py`

ORM model for ML training feedback or strategy outcome tracking data.

### `app/models/schemas/__init__.py`

Schema package marker.

### `app/models/schemas/analytics.py`

Pydantic schemas for analytics responses and dashboard data contracts.

### `app/models/schemas/borrower.py`

Pydantic schemas for borrower create/update/read APIs.

### `app/models/schemas/call.py`

Pydantic schemas for AI call requests and responses.

### `app/models/schemas/call_analysis.py`

Pydantic schemas for call analysis data returned to clients.

### `app/models/schemas/campaign.py`

Pydantic schemas for campaign request and response payloads.

## 6.8 `app/monitoring/`

### `app/monitoring/__init__.py`

Package marker for observability utilities.

### `app/monitoring/health.py`

Health-check logic for liveness/readiness style checks.

### `app/monitoring/metrics.py`

Prometheus or metrics instrumentation setup for API and call-processing visibility.

## 6.9 `app/services/`

### `app/services/__init__.py`

Package marker for service-layer modules.

### `app/services/compliance/__init__.py`

Package marker for compliance services.

### `app/services/compliance/consent_manager.py`

Manages consent validation and consent-related business rules before communication.

### `app/services/compliance/fdcpa_guard.py`

Runtime compliance gate that checks whether a call is allowed based on debt collection rules, contact conditions, time windows, borrower status, and other restrictions.

### `app/services/compliance/opt_out_handler.py`

Handles opt-out, do-not-call, and dispute-style actions or detected language from borrowers.

### `app/services/follow_up/__init__.py`

Package marker for follow-up features.

### `app/services/follow_up/follow_up_brief.py`

Builds the personalized follow-up brief shown before a follow-up call starts. It summarizes the previous call, identifies useful follow-up points, and generates an opener/focus hint.

### `app/services/follow_up/follow_up_call.py`

Specialized follow-up call helper. It builds more human-like follow-up openers and guidance from previous call context so repeat calls do not sound like cold starts.

### `app/services/llm/__init__.py`

Package marker for LLM integrations.

### `app/services/llm/function_registry.py`

Registry of callable tools/functions available to the LLM or orchestrator during conversations.

### `app/services/llm/gpt4o_client.py`

Client wrapper around the OpenAI model used for live reasoning or prompt execution.

### `app/services/llm/prompt_builder.py`

Builds the live system prompts and contextual prompt fragments used during calls. This is where agent persona, compliance language, borrower context, and negotiation strategy are combined.

### `app/services/memory/__init__.py`

Package marker for memory and state services.

### `app/services/memory/redis_session.py`

Stores and retrieves live call session state, transient memory, and related runtime data in Redis.

### `app/services/memory/vector_store.py`

Vector-memory or semantic retrieval helper, likely used to store or search context embeddings.

### `app/services/ml/__init__.py`

Package marker for runtime ML services.

### `app/services/ml/feature_extractor.py`

Builds model features from borrower and call data for strategy or outcome prediction.

### `app/services/ml/outcome_tracker.py`

Records repayment or contact outcomes to support model feedback loops and performance tracking.

### `app/services/ml/strategy_engine.py`

Selects or recommends the next collection strategy based on borrower state, prior outcomes, and ML features.

### `app/services/profiling/__init__.py`

Package marker for borrower profiling services.

### `app/services/profiling/behavioral_tracker.py`

Tracks behavioral patterns across calls, such as avoidance, responsiveness, or reliability indicators.

### `app/services/profiling/borrower_scorer.py`

Computes borrower-level scores like engagement, repayment likelihood, or prioritization metrics.

### `app/services/profiling/sentiment_analyzer.py`

Extracts sentiment and conversational signals from transcripts, including payment language, hardship markers, and amount mentions.

### `app/services/scheduling/__init__.py`

Package marker for scheduling logic.

### `app/services/scheduling/call_scheduler.py`

Determines when calls should be placed based on timing rules, borrower windows, and campaign settings.

### `app/services/scheduling/campaign_runner.py`

Executes campaign-level calling logic and coordinates batches of scheduled outreach.

### `app/services/stt/__init__.py`

Package marker for speech-to-text services.

### `app/services/stt/deepgram_client.py`

Client wrapper around Deepgram for streaming or batch transcription.

### `app/services/telephony/__init__.py`

Package marker for telephony services.

### `app/services/telephony/call_controller.py`

High-level call control service that likely starts, ends, routes, and manages call lifecycles.

### `app/services/telephony/twilio_client.py`

Integration wrapper for Twilio telephony APIs and webhook handling.

### `app/services/tts/__init__.py`

Package marker for text-to-speech services.

### `app/services/tts/elevenlabs_client.py`

Client wrapper for ElevenLabs speech synthesis used to voice the AI agent.

## 6.10 `app/utils/`

### `app/utils/__init__.py`

Package marker for utility helpers.

### `app/utils/audio_utils.py`

Audio conversion, formatting, or transport-related helpers used in the realtime media pipeline.

### `app/utils/crypto.py`

Small encryption, hashing, or security utility helpers.

### `app/utils/phone_utils.py`

Phone normalization and validation helpers, likely built around E.164 formatting and hashing.

### `app/utils/retry.py`

Retry helpers or reusable resilience wrappers for unstable external operations.

## 6.11 `app/workers/`

### `app/workers/__init__.py`

Package marker for Celery workers.

### `app/workers/analytics_tasks.py`

Background tasks for analytics aggregation or periodic reporting.

### `app/workers/call_tasks.py`

Background tasks related to call execution, follow-up work, or async call processing.

### `app/workers/celery_app.py`

Celery application setup, queue configuration, and shared worker bootstrap.

### `app/workers/ml_tasks.py`

Background tasks for model scoring, retraining triggers, or ML housekeeping.

### `app/workers/notification_tasks.py`

Background tasks for alerts, notifications, or operator-facing async messaging.

## 6.12 `docker/`

### `docker/Dockerfile.api`

Docker build recipe for the FastAPI application container.

### `docker/Dockerfile.worker`

Docker build recipe for Celery worker and beat services.

### `docker/nginx/nginx.conf`

Nginx configuration file, likely used for reverse proxying API/frontend traffic in a containerized deployment.

## 6.13 `frontend/`

### `frontend/README.md`

Frontend-specific setup notes and developer instructions.

### `frontend/package.json`

Frontend package manifest defining the React/Vite toolchain, runtime dependencies, and scripts like `dev`, `build`, `lint`, and `preview`.

### `frontend/package-lock.json`

Generated npm lockfile that freezes exact frontend dependency versions for reproducible installs.

### `frontend/postcss.config.js`

PostCSS configuration for the frontend styling pipeline.

### `frontend/eslint.config.js`

ESLint configuration for TypeScript/React linting.

### `frontend/index.html`

Vite HTML entry document used to bootstrap the React SPA.

### `frontend/tsconfig.json`

Base TypeScript configuration for the frontend workspace.

### `frontend/tsconfig.app.json`

TypeScript configuration for the browser application code.

### `frontend/tsconfig.node.json`

TypeScript configuration for Node-oriented config files used by the frontend toolchain.

### `frontend/vite.config.ts`

Vite build and dev-server configuration.

### `frontend/public/favicon.svg`

Public favicon served as a static asset.

### `frontend/public/icons.svg`

Shared icon asset served directly by the frontend.

### `frontend/src/main.tsx`

React entrypoint that mounts the app to the DOM.

### `frontend/src/App.tsx`

Top-level frontend router and app shell composition. It wires route pages for dashboard, borrowers, calls, campaigns, compliance, call quality, and human-call views.

### `frontend/src/App.css`

Application-level CSS for the React app shell.

### `frontend/src/index.css`

Global stylesheet and shared design tokens or reset styles for the frontend.

### `frontend/src/api/client.ts`

Shared HTTP client setup, likely based on Axios, with base URL and common request helpers.

### `frontend/src/api/analytics.ts`

Frontend API wrapper for analytics endpoints.

### `frontend/src/api/borrowers.ts`

Frontend API wrapper for borrower endpoints.

### `frontend/src/api/calls.ts`

Frontend API wrapper for AI call endpoints, including call detail and follow-up interactions.

### `frontend/src/api/campaigns.ts`

Frontend API wrapper for campaign endpoints.

### `frontend/src/api/compliance.ts`

Frontend API wrapper for compliance endpoints.

### `frontend/src/api/human_calls.ts`

Frontend API wrapper for human-call endpoints.

### `frontend/src/assets/hero.png`

Visual asset used in the frontend UI.

### `frontend/src/assets/react.svg`

React logo asset from the starter setup.

### `frontend/src/assets/vite.svg`

Vite logo asset from the starter setup.

### `frontend/src/components/layout/AppShell.tsx`

Reusable layout wrapper that structures page chrome and navigation areas.

### `frontend/src/components/layout/Sidebar.tsx`

Sidebar navigation component for moving across major operator pages.

### `frontend/src/components/ui/Badge.tsx`

Reusable badge/pill component for statuses and labels.

### `frontend/src/components/ui/Button.tsx`

Reusable button component with shared styling variants.

### `frontend/src/components/ui/Card.tsx`

Reusable card container component for dashboard and detail layouts.

### `frontend/src/components/ui/Input.tsx`

Reusable form input component.

### `frontend/src/components/ui/Modal.tsx`

Reusable modal/dialog component.

### `frontend/src/components/ui/Spinner.tsx`

Reusable loading indicator component.

### `frontend/src/lib/utils.ts`

Shared frontend utility helpers such as class merging and display formatting. This file also handles user-facing currency formatting.

### `frontend/src/pages/Dashboard.tsx`

Main dashboard page showing high-level operational metrics and summaries.

### `frontend/src/pages/Compliance.tsx`

Compliance review page for DNC, opt-out, consent, or related operational status.

### `frontend/src/pages/CallQuality.tsx`

Call quality and analytics page, likely focused on performance or conversation quality views.

### `frontend/src/pages/Borrowers/BorrowerList.tsx`

Borrower list/table page.

### `frontend/src/pages/Borrowers/BorrowerDetail.tsx`

Borrower detail page showing borrower profile, account details, contact state, and likely call history context.

### `frontend/src/pages/Borrowers/BorrowerForm.tsx`

Borrower create/edit form page.

### `frontend/src/pages/Calls/CallList.tsx`

AI call history list page.

### `frontend/src/pages/Calls/CallDetail.tsx`

AI call detail page showing transcript, analysis, and follow-up initiation workflow.

### `frontend/src/pages/Campaigns/CampaignList.tsx`

Campaign listing page.

### `frontend/src/pages/Campaigns/CampaignDetail.tsx`

Campaign detail page with status and borrower/call information for a selected campaign.

### `frontend/src/pages/Campaigns/CampaignForm.tsx`

Campaign creation/edit form page.

### `frontend/src/pages/HumanCalls/HumanCallList.tsx`

Human-call history list page.

### `frontend/src/pages/HumanCalls/HumanCallDetail.tsx`

Human-call detail page.

## 6.14 `infra/`

The `infra` folder currently has no tracked files. It is a placeholder for future infrastructure code.

## 6.15 `migrations/`

### `migrations/env.py`

Alembic migration environment bootstrap. It connects migration execution to the project’s SQLAlchemy metadata and database settings.

### `migrations/script.py.mako`

Alembic template used when generating new migration files.

### `migrations/versions/0001_initial_schema.py`

Initial database schema migration that creates the foundational tables.

### `migrations/versions/0002_call_intelligence.py`

Schema update adding post-call intelligence related structures.

### `migrations/versions/0003_separate_human_calls.py`

Migration that separates human-call records from AI call records.

### `migrations/versions/0004_human_calls_contact_fields.py`

Migration that extends human-call tables with additional contact-related fields.

### `migrations/versions/0005_ai_call_analysis.py`

Migration that adds AI call analysis related schema changes.

## 6.16 `ml/`

### `ml/training/__init__.py`

Package marker for training code.

### `ml/training/train_strategy_model.py`

Offline model training entrypoint for the collection strategy model.

## 6.17 `scripts/`

### `scripts/run_campaign.py`

Manual script to launch or simulate a campaign run outside the UI.

### `scripts/seed_borrowers.py`

Seed script that populates the database with borrower sample data.

## 6.18 `static/`

### `static/favicon.svg`

Backend-served favicon asset.

### `static/icons.svg`

Backend-served icon sprite or shared static icon file.

### `static/index.html`

Static HTML shell used when serving the frontend through the backend.

## 6.19 `tests/`

### `tests/__init__.py`

Package marker for tests.

### `tests/conftest.py`

Shared pytest fixtures and test setup logic.

### `tests/unit/test_barge_in_detector.py`

Unit tests for the barge-in detection logic.

### `tests/unit/test_fdcpa_guard.py`

Unit tests for the compliance guard behavior.

### `tests/unit/test_prompt_builder.py`

Unit tests for prompt assembly and live agent prompt rules.

### `tests/unit/test_sentiment_analyzer.py`

Unit tests for transcript sentiment and signal extraction.

## 7. Architectural Notes

### Strengths of the current structure

- Clear separation between API, orchestration, service integrations, models, and frontend.
- Good layering for realtime voice operations: telephony, STT, LLM, TTS, memory, and compliance are separated into dedicated service modules.
- Separate AI-call and human-call flows make the system easier to evolve.
- Migrations, tests, scripts, and worker modules are already organized in maintainable locations.

### Areas that stand out for future cleanup

- A few local artifacts live at the repo root, such as the executable and log file.
- `infra/` is empty, which suggests deployment/infrastructure code has not yet been formalized.
- Some assets and starter files still look inherited from template scaffolding, which can be trimmed if not needed.

## 8. Suggested Reading Order For New Developers

If someone is new to the project, this is the fastest order to understand it:

1. `pyproject.toml` and `requirements.txt`
2. `app/main.py`
3. `app/config.py`
4. `app/api/v1/router.py`
5. `app/api/websocket/media_stream.py`
6. `app/core/session_orchestrator.py`
7. `app/services/llm/prompt_builder.py`
8. `app/services/telephony/twilio_client.py`
9. `app/models/database/*`
10. `frontend/src/App.tsx`
11. `frontend/src/api/*`
12. `frontend/src/pages/Calls/CallDetail.tsx`

## 9. Final Takeaway

This repository is a full-stack AI debt collection platform, not just a prompt wrapper. It combines:

- backend APIs
- realtime voice orchestration
- compliance enforcement
- data persistence
- post-call intelligence
- campaign automation
- human-call workflows
- frontend operations tooling

The strongest technical center of gravity is the realtime call pipeline built around `media_stream.py`, `session_orchestrator.py`, `prompt_builder.py`, and the telephony/STT/TTS integration services. The rest of the repository supports that core capability with persistence, analytics, campaign management, and operator UI.
