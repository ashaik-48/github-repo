# PR Agent - Project Summary

## What This Project Does

**PR Agent** is a webhook-driven risk analysis service for GitHub pull requests.

When a PR is created/updated, GitHub sends a webhook → the service analyzes the PR (metadata, diffs, rules) → calculates a risk score → stores results in PostgreSQL.

Clients can then query analysis results via REST API.

## Architecture Overview

```
GitHub PR Event
    ↓
POST /webhooks/github (receives webhook)
    ↓
Webhook Ingest Node (validates signature, filters events)
    ↓
Metadata Collection Node (extracts PR info from webhook + GitHub API)
    ↓
Diff Extraction Node (fetches file changes from GitHub API)
    ↓
Rules Loading Node (loads scoring rules for the repo)
    ↓
Risk Calculation Node (applies rules, computes score & findings)
    ↓
Persistence Node (stores event, analysis, findings in PostgreSQL)
    ↓
Query via GET /pr-analysis/{owner}/{repo}/{pr_number}
```

---

## Core Components Built

### 1. **FastAPI Application** ([app/main.py](app/main.py))
- Entry point for the service
- Initializes database on startup
- Mounts routers (webhooks, analysis)
- Health check endpoint

### 2. **Webhook Router** ([app/routers/webhooks.py](app/routers/webhooks.py))
- **POST /webhooks/github** - Receives GitHub webhook events
- Validates X-Hub-Signature-256 (HMAC-SHA256)
- Filters for pull_request events (opened, synchronize, reopened actions)
- Runs analysis pipeline asynchronously in background
- Returns immediate acknowledgement

### 3. **Analysis Router** ([app/routers/analysis.py](app/routers/analysis.py))
- **GET /pr-analysis/{owner}/{repo}/{pr_number}** - Fetch latest analysis for a PR
- **GET /pr-analysis/{analysis_id}** - Fetch analysis by ID
- Returns risk score, level, findings, and PR metadata

### 4. **PR Analysis Pipeline** ([app/pr_pipeline/](app/pr_pipeline/))

**Graph** ([graph.py](app/pr_pipeline/graph.py)) - Orchestrates 6-stage pipeline:

#### Stage 1: Ingest ([nodes/ingest.py](app/pr_pipeline/nodes/ingest.py))
- Validates webhook signature
- Filters non-pull_request events
- Filters unsupported PR actions (only processes: opened, synchronize, reopened)
- Sets initial status (accepted/ignored/rejected)

#### Stage 2: Metadata Collection ([nodes/metadata.py](app/pr_pipeline/nodes/metadata.py))
- Extracts PR info from webhook payload:
  - owner, repo, PR number, title, body
  - author, base/head branch, SHAs
  - commit count, file count, additions/deletions
  - labels, draft status
- Optional GitHub API call to enrich metadata if token provided
- Skips if PR was ignored/rejected

#### Stage 3: Diff Extraction ([nodes/diff.py](app/pr_pipeline/nodes/diff.py))
- Calls GitHub API to list PR files
- For each file extracts:
  - file_path, status (added/modified/deleted)
  - additions/deletions count
  - patch content (first 12KB)
- Skips if GitHub API call fails (graceful degradation)
- Updates metadata if counts were zero

#### Stage 4: Rules Loading ([nodes/rules.py](app/pr_pipeline/nodes/rules.py))
- Loads scoring rules for the repo (owner/repo)
- Tries repo-specific rules from DB first
- Falls back to default rules from [rules/default_rules.json](rules/default_rules.json)
- Skips if PR was ignored/rejected

#### Stage 5: Risk Calculation ([nodes/risk.py](app/pr_pipeline/nodes/risk.py))
- Applies scoring logic using rules
- Generates findings (violations/concerns)
- Returns score (0–100), level (low/medium/high/critical), and factors
- Skips if PR was ignored/rejected

**Scoring Logic** ([scoring.py](app/scoring.py)):
- **High file count**: +15 pts if ≥20 files changed
- **High churn**: +15 pts if ≥800 total lines changed
- **Sensitive paths**: +25 pts per sensitive file touched (e.g., auth, config)
- **No test coverage**: +15 pts if source changed but no test files touched
- Risk level mapping: 0–24 = low, 25–49 = medium, 50–74 = high, 75+ = critical

#### Stage 6: Persistence ([nodes/persist.py](app/pr_pipeline/nodes/persist.py))
- Inserts webhook event into pr_events table
- Inserts analysis record into pr_analyses table (score, level, summary)
- Inserts findings into pr_findings table (rule violations)
- Generates human-readable summary
- Returns analysis_id for future queries

### 5. **Database Schema** ([app/database.py](app/database.py))

**pr_events** - Webhook audit log
```
id, delivery_id (unique), event_type, action, owner, repo, pr_number, 
received_at, raw_payload_json
```

**pr_analyses** - Risk analysis results
```
id, owner, repo, pr_number, head_sha, base_sha, files_changed, 
additions, deletions, risk_score, risk_level, summary, created_at
```

**pr_findings** - Per-rule violations
```
id, analysis_id, rule_id, severity, message, file_path, 
line_start, line_end, evidence_json
```

**repo_rules** - Custom rules per repo (optional)
```
id, owner, repo, rules_json, updated_at (unique on owner+repo)
```

### 6. **Configuration** ([app/config.py](app/config.py))
Loads from `.env`:
- HOST, PORT (server)
- GITHUB_WEBHOOK_SECRET (validate X-Hub-Signature-256)
- GITHUB_API_TOKEN (call GitHub API for metadata/diffs)
- DATABASE_URL (PostgreSQL connection URL)
- DEFAULT_RULES_FILE (fallback rules)

### 7. **Rules System** ([app/rules_loader.py](app/rules_loader.py) + [rules/default_rules.json](rules/default_rules.json))
- Weights: point values for each risk factor
- Thresholds: numeric boundaries (high_file_count, high_churn_lines)
- Sensitive path prefixes: paths triggering high-severity findings
- Test path markers: patterns for test files

### 8. **GitHub Client** ([app/github_client.py](app/github_client.py))
- Async wrapper around GitHub API
- Methods:
  - `get_pull_request(owner, repo, pr_number)` → PR details
  - `list_pull_files(owner, repo, pr_number)` → file diffs

### 9. **State Model** ([app/pr_pipeline/state.py](app/pr_pipeline/state.py))
Pydantic models for pipeline state flow:
- PRWebhookEnvelope (received webhook + headers)
- PRMetadata (PR details)
- PRFileDiff (file change info)
- RuleFinding (score finding/violation)
- RiskScore (computed risk)
- PRAgentState (aggregates all above)

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |
| POST | `/webhooks/github` | Receive GitHub webhook (runs pipeline async) |
| GET | `/pr-analysis/{owner}/{repo}/{pr_number}` | Fetch latest analysis for PR |
| GET | `/pr-analysis/{analysis_id}` | Fetch analysis by ID |

---

## How to Run

### Prerequisites
- Python 3.7+
- pip

### Steps

1. **Create and activate virtualenv**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**
   ```bash
   python -m pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp sample_env.txt .env
   # Edit .env and fill in:
   #   GITHUB_WEBHOOK_SECRET=<your-webhook-secret>
   #   GITHUB_API_TOKEN=<your-github-pat>
   ```

4. **Start server**
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
   ```

5. **Verify**
   ```bash
   curl http://127.0.0.1:8010/health
   ```

### Register GitHub Webhook
- Go to your repo settings → Webhooks
- Payload URL: `http://<your-host>:8010/webhooks/github`
- Content type: `application/json`
- Secret: value of `GITHUB_WEBHOOK_SECRET` in `.env`
- Events: Select "Pull requests"
- Active: ✓

---

## Processing Flow Example

1. Developer opens PR on GitHub
2. GitHub sends webhook to `/webhooks/github`
3. Service returns 202 (accepted) immediately
4. Pipeline runs in background (async):
   - Validates signature ✓
   - Extracts metadata (title, author, SHAs, etc.)
   - Fetches file diffs from GitHub API
   - Loads scoring rules
   - Applies rules → calculates risk_score, risk_level, findings
    - Stores in PostgreSQL (event, analysis, findings)
5. Client calls `GET /pr-analysis/{owner}/{repo}/{pr_number}`
6. Service returns analysis + findings

---

## Key Design Decisions

1. **Async Pipeline**: Webhook handler returns immediately; pipeline runs in background. First fetch may briefly return 404 (expected behavior while processing).

2. **Graceful Degradation**: If GitHub API fails, analysis continues with webhook payload data.

3. **Stateless Nodes**: Each pipeline stage is independent; state is immutable.

4. **Rule-Driven Scoring**: Risk calculation is 100% configurable via rules JSON.

5. **PostgreSQL for Durability**: relational storage with migrations, FK constraints, and indexing.

6. **Signature Validation**: Verifies authenticity of GitHub webhook using HMAC-SHA256.

---

## Current Status

✅ End-to-end pipeline validated locally
✅ Database persistence working
✅ Webhook ingest + async execution working
✅ Analysis retrieval working
✅ All 6 pipeline stages integrated

---

## Future Enhancements (Optional)

- Add a queued status endpoint so clients can poll until analysis is ready
- Add webhook retry logic (exponential backoff)
- Add support for other event types (issues, pull_request_review, etc.)
- Add authentication for sensitive endpoints
- Add webhooks for pushing analysis to external systems (Slack, GitHub PR comments, etc.)
- Add UI dashboard to browse analyses
