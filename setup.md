# PR Agent Setup

Complete setup and configuration guide for the PR Agent service.

## Environment & Versions

| Component | Version |
| --- | --- |
| Python | 3.13.1 |
| pip | 26.1.2 |
| OS (tested) | macOS |

### Core dependencies (pinned to installed versions)

| Package | Version |
| --- | --- |
| fastapi | 0.136.3 |
| uvicorn[standard] | 0.49.0 |
| pydantic | 2.13.4 |
| pydantic-settings | 2.14.1 |
| httpx | 0.28.1 |
| python-dotenv | 1.2.2 |
| langgraph | 1.2.5 |
| langchain | 1.3.9 |
| litellm | 1.89.1 |
| PyGithub | 2.9.1 |
| SQLAlchemy | 2.0.51 |
| psycopg2-binary | 2.9.12 |
| redis | 8.0.0 |
| prometheus-client | (installed) |

> Requires **Python 3.13+**. On this machine `python` may not be on PATH — use `python3` / `python3.13`.

## 1. Create virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python --version   # should print Python 3.13.1
```

## 2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. Start PostgreSQL and create database

createdb pr_agent

4. Configure env

```bash
cp sample_env.txt .env
```

Then edit `.env`. All settings have defaults (defined in [app/config.py](app/config.py)), so the server runs locally without any configuration, but the following are commonly set:

### Server
| Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Bind address for uvicorn |
| `PORT` | `8010` | Bind port for uvicorn |

### GitHub
| Variable | Default | Description |
| --- | --- | --- |
| `GITHUB_WEBHOOK_SECRET` | `""` | Validates `X-Hub-Signature-256` |
| `GITHUB_API_TOKEN` | `""` | Token for PR metadata and changed files |
| `GITHUB_API_BASE_URL` | `https://api.github.com` | GitHub API base URL |

### GitLab
| Variable | Default | Description |
| --- | --- | --- |
| `GITLAB_WEBHOOK_SECRET` | `""` | Validates `X-Gitlab-Token` |
| `GITLAB_API_TOKEN` | `""` | Token for MR metadata and changed files |
| `GITLAB_API_BASE_URL` | `https://gitlab.com/api/v4` | GitLab API base URL |

### Storage
| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_PATH` | `./data/pr_agent.db` | SQLite database file path |
| `DEFAULT_RULES_FILE` | `./rules/default_rules.json` | Fallback rules when repo rules not in DB |
| `REVIEW_GUIDELINES_FILE` | `./rules/review_guidelines.md` | Review guidelines file |

### Review comments
| Variable | Default | Description |
| --- | --- | --- |
| `POST_COMMENTS_ENABLED` | `false` | Enable posting inline review comments |
| `MAX_INLINE_COMMENTS` | `20` | Max inline comments per review |

### LLM
| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | Provider: `openai` \| `claude` \| `gemini` |
| `LLM_TIMEOUT_SECONDS` | `30` | LLM request timeout |
| `OPENAI_API_KEY` | `""` | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key |
| `CLAUDE_MODEL` | `claude-3-5-sonnet-20241022` | Claude model |
| `GEMINI_API_KEY` | `""` | Gemini API key |
| `GEMINI_MODEL` | `gemini/gemini-1.5-pro` | Gemini model |
| `OLLAMA_ENABLED` | `false` | Enable local Ollama provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `ollama/llama3` | Ollama model |

> Security note: do not commit real secrets. Keep `.env` out of version control and rotate any tokens that were previously shared in plaintext.

## 4. Run the API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

If port 8010 is already in use, free it with:

```bash
lsof -ti:8010 | xargs kill -9
```

## 5. Register GitHub webhook

- Payload URL: `http://<host>:8010/webhooks/github`
- Content type: `application/json`
- Secret: value of `GITHUB_WEBHOOK_SECRET`
- Events: Pull requests

## 6. Register GitLab webhook

- URL: `http://<host>:8010/webhooks/gitlab`
- Secret token: value of `GITLAB_WEBHOOK_SECRET`
- Trigger events: Merge request events

## 7. Configure API tokens

- Set `GITHUB_API_TOKEN` for GitHub PR metadata and changed files
- Set `GITLAB_API_TOKEN` for GitLab MR metadata and changed files

## 8. Query analysis

- `GET /pr-analysis/{owner}/{repo}/{pr_number}`
- Optional filter: `GET /pr-analysis/{owner}/{repo}/{pr_number}?provider=github|gitlab`
- `GET /pr-analysis/{analysis_id}`

## 9. For windows

- Use Windows commands for setup
