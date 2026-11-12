# SEO Metadata Intelligence Platform

Crawl any website, extract its meta titles and descriptions, understand each page with AI, audit the existing
metadata, generate page-specific replacements under each website's own brand guidelines and guardrails, validate
every proposal independently, and review, approve and export the results.

**Nothing is ever published to a live website.** The platform only produces recommendations and exports.

---

## Architecture

```
frontend/  Next.js 16 + TypeScript + Tailwind (shadcn-style components)   :3000
   │  /api/* proxied by Next rewrites
backend/   FastAPI + SQLAlchemy 2 + Alembic                                 :8000
   ├── app/crawler/   URL discovery, SSRF-safe fetching, robots.txt, sitemaps, Playwright rendering, extraction
   ├── app/seo/       guideline context, deterministic rules, 0-100 scoring, duplicate/overlap detection
   ├── app/ai/        provider abstraction (Anthropic / OpenAI), prompts + strict JSON schemas, pipeline
   ├── app/services/  Excel / CSV exports
   ├── app/api/       REST routers (auth, projects, guidelines, crawls, pages/review, ai, exports, settings)
   └── app/worker.py  Celery tasks (crawl, AI jobs)
PostgreSQL (data)   Redis (Celery broker)   Celery worker (long-running jobs)
```

Long-running work (crawling, AI processing) runs in Celery workers, so the UI never blocks. Crawl progress is stored
in the database (`pages` is the crawl frontier), so a crawl can be paused, resumed after a worker restart, or stopped.

### End-to-end workflow

1. **Website Projects**: add a website (name, URL, market, language, country, audience, category, crawl and AI settings).
2. **Brand SEO Intelligence**: brand context (A), SEO guidelines (B), mandatory guardrails (C), custom instructions (D)
   and mandatory keywords. Every save creates a new version; old versions can be viewed and restored.
3. **Crawl Manager**: discovers URLs from robots.txt sitemaps, sitemap indexes (incl. `.xml.gz`), internal links,
   canonicals, pagination (`rel=next/prev`, `?page=`), redirects, manual URLs and uploaded `.txt/.csv` lists.
4. Extraction stores title, description, canonical, meta robots + X-Robots-Tag, H1/H2/headings, language, OG tags,
   indexability, word count, cleaned main content (navigation, header, footer, cookie banners, scripts, hidden and
   UI boilerplate removed), intro, JSON-LD types, product names and brand mentions.
5. A **deterministic audit** of existing metadata runs automatically when the crawl finishes (no AI needed).
6. **AI Optimisation** runs separate stages per page:
   1. *Page understanding*: page type, topic, intent, audience, primary/secondary keywords, entities, USPs (each USP
      must quote evidence from the page, otherwise it is dropped), key message, and whether content is sufficient.
   2. *Existing metadata evaluation*: semantic scores and issues, merged with the rule-based audit.
   3. *Generation*: uses the website's guidelines, page content, page type, intent, keywords, existing issues and
      similar pages on the site (for differentiation). Every claim must include a verbatim evidence quote.
   4. *Independent validation*: deterministic checks first (lengths, prohibited words/phrases/claims, competitor
      brands, must-use words, formatting, brand placement/casing, stuffing, duplicates, claim evidence); only if those
      pass does a separate AI reviewer judge accuracy, brand voice, custom instructions, page-type rules, keyword use,
      naturalness and unsupported claims.
   5. *Regeneration*: failures are sent back with the exact problems, up to the configured number of attempts; after
      that the page is flagged **failed / manual review**.
   A final site-wide pass re-differentiates any proposals that still duplicate another page.
7. **Approval Queue / Metadata Audit**: the 18-column table (search, sort, filters), detail panel (review, audit
   findings, page context, full history), approve both / title only / description only, edit, reject, regenerate
   (title / description / both) with feedback, bulk approve / regenerate.
8. **Reports & Exports**: Complete audit, Approved only, Needs improvement, Missing metadata, Duplicates, Crawl errors,
   each as Excel (frozen headers, filters, readable widths, wrapped text, multiple sheets) or UTF-8 CSV.

### Guarantees built into the code

| Requirement | How it is enforced |
| --- | --- |
| Website guidelines never leak across projects | Every AI prompt is built from a `ProjectContext` loaded for one `project_id`; every API route resolves the project through `get_project` (owner check). Tested in `tests/test_pipeline.py::test_guidelines_are_isolated_per_project` and `tests/test_api.py::test_projects_are_isolated_between_users`. |
| Never approve metadata violating a mandatory guardrail | Approval re-runs deterministic checks; any guardrail/formatting violation returns HTTP 422 and nothing is approved. Bulk approval skips such pages and reports why. |
| Never invent facts | Prompts forbid it; USPs and generated claims need verbatim evidence from the page; the reviewer lists unsupported claims (blocking). |
| Thin pages are not guessed | Pages below the min-word threshold without an H1, or judged insufficient by the AI, get status `needs_review` and no AI copy. |
| No duplicate AI spend | Analysis and generation are fingerprinted (prompt version, model, content hash, existing metadata, guideline version); unchanged pages are skipped unless "force" is set. |
| Failed URLs are never discarded | Every URL keeps its status (`failed`, `blocked`, `redirected`, `skipped`, `duplicate`) with HTTP code and error; all appear in the Crawl Errors export and the crawl log. |
| No integration pretends to work | Without an API key, AI jobs are refused with HTTP 412 and a setup message. Provider errors (401, 404 model, rate limits, refusals, truncation) surface as clear job errors. |

### Scoring framework (transparent, 0-100)

| Title (100) | pts | Description (100) | pts |
| --- | --- | --- | --- |
| Length within configured range | 20 | Length within configured range | 20 |
| Estimated display width (≤580px) | 10 | Primary + secondary keywords | 15 |
| Primary keyword present / early | 20 | Relevance to page content | 25 |
| Relevance to page content | 20 | Uniqueness across the site | 15 |
| Uniqueness across the site | 15 | Value proposition / clarity | 15 |
| Brand naming convention | 5 | Natural language (no stuffing, claims) | 10 |
| Writing quality (stuffing, generic, guardrails) | 10 | | |

Overall = 50% title + 50% description. Relevance/appeal use the AI evaluation when available, otherwise a
token-overlap heuristic; the detail panel shows every component and which method was used. A critical guardrail
violation caps the affected score at 40. **Scores are an internal quality assessment; they do not guarantee rankings
or CTR.**

---

## Setup

### Option A: Docker Compose

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env`: set `SECRET_KEY` and `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`. Then:

```bash
docker compose up --build
```

Open http://localhost:3000, create an account, add a website.

### Option B: Local development

Requirements: Python 3.11+, Node 20+, PostgreSQL 14+, Redis 6+.

```bash
cd backend
python -m venv ../.venv && . ../.venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

```bash
createdb seo_metadata
```

```bash
alembic upgrade head
```

```bash
uvicorn app.main:app --reload --port 8000
```

In a second terminal (same virtualenv, `backend/` directory):

```bash
celery -A app.worker.celery_app worker --loglevel=info --concurrency=4
```

In a third terminal:

```bash
cd frontend && npm install && npm run dev
```

API docs: http://localhost:8000/api/docs. For a quick single-process trial you can set `TASK_BACKEND=inline`
(jobs run in a background thread of the API; not for production).

### AI providers

Set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in `backend/.env`, or save a key per user under **Settings** (encrypted
at rest with a key derived from `SECRET_KEY`, never returned by the API). Per website you can choose provider, model,
reasoning effort (Claude), max validation attempts, AI concurrency and the minimum word count.

* Anthropic defaults to `claude-opus-5-5` with strict JSON-schema structured outputs, a cached per-project system
  prompt, and server-side refusal fallbacks enabled (`server-side-fallback-2026-07-01`, `fallbacks: "default"`).
  Refusals and truncated outputs are detected and reported, never parsed as results.
* OpenAI uses `response_format: json_schema` with `strict: true`. The default model name is configurable via
  `DEFAULT_OPENAI_MODEL`.
* Token usage and estimated cost are logged per call (`ai_usage_logs`) and shown under AI Optimisation and Settings.
  Prices live in `PRICING` in `backend/app/ai/providers.py`; update them when provider pricing changes.

### Tests

```bash
cd backend
createdb seo_metadata_test
```

```bash
TEST_DATABASE_URL=postgresql+psycopg://seo:seo@localhost:5432/seo_metadata_test python -m pytest
```

36 tests cover URL normalisation, SSRF blocking, extraction/boilerplate removal, indexability, rule checks and
scoring, a full crawl against a local fixture website (sitemap index, robots.txt block, redirects, 404/500 with
retries, noindex, pagination, tracking-parameter removal, max-URL limit, resume after interruption), the AI pipeline
with a deterministic fake provider (validation, regeneration on guardrail failure, max-attempt escalation,
insufficient content, caching, cross-project isolation), and the API (auth, ownership isolation, guideline
versioning, filters/sorting, edit/approve/block workflow, bulk approve, all six exports in both formats).

---

## Security notes

* **SSRF protection**: every request (and every redirect hop, and every sub-request made by the headless browser)
  is checked: only http/https, no credentials in URLs, no localhost/`.internal`/metadata hostnames, no numeric-encoded
  hosts, and the resolved IPs must not be private, loopback, link-local, CGNAT, multicast or reserved (IPv4 and IPv6,
  including IPv4-mapped). `ALLOW_PRIVATE_NETWORKS=true` exists only for local testing.
  The check resolves DNS before connecting; a determined DNS-rebinding attacker could still race it, so run workers in
  a network segment without access to internal services for defence in depth.
* Crawling respects robots.txt (including `Crawl-delay`), treats a 5xx robots.txt as "disallow all", stays within the
  project domain (optionally subdomains / extra hosts), and never attempts to bypass logins, CAPTCHAs or paywalls.
* Passwords are bcrypt-hashed; sessions use signed JWTs; the app refuses to start in production with the default
  `SECRET_KEY`. Set `ALLOW_REGISTRATION=false` once your accounts exist.
* Exports neutralise spreadsheet formula injection (cells starting with `=` are stored as text in Excel; CSV prefixes
  `= + @` with `'`).
* Page content is treated as data: prompts instruct the model to ignore instructions embedded in crawled pages.
* An audit log records project, guideline, crawl, AI, approval, credential and export actions.

## Data model

`users`, `provider_credentials`, `projects`, `guideline_versions` (brand guidelines, SEO guidelines, guardrails,
keywords, custom instructions, versioned), `crawl_jobs`, `crawl_logs`, `pages` (discovered URLs, crawl results,
approval state), `page_contents` (existing metadata + extracted content), `page_analyses` (AI understanding),
`audit_results` (existing and proposed scores + findings), `metadata_versions` (every AI/regenerated/manual proposal),
`validation_results` (every attempt), `approval_events`, `ai_jobs`, `ai_usage_logs`, `export_history`, `audit_logs`.
Migrations: `backend/alembic/versions/`.

## Known limitations

* Approval does not re-run the AI reviewer on manual edits (deterministic checks only); regenerate to get a full AI
  validation.
* JavaScript rendering is used automatically only when a page looks client-side rendered (or always, if configured);
  it is slower and heavier than plain HTTP fetching.
* Near-duplicate detection uses token overlap and sequence similarity, not embeddings.
* SERP preview and pixel-width estimates are approximations of Google's display.
