# Retail Pulse — Setup & Build Guide (Ideation by Opus/top model, Build by Sonnet in VS Code)

This document is the blueprint only. No code is included here — you build everything locally
in VS Code using Claude Code (Sonnet), following the structure and prompts below in order.

---

## 1. Product Definition

**Name:** Retail Pulse
**What it is:** An internal tool that converts weekly retail transaction data into an
automated, plain-English analyst report — trends, anomalies, and recommended actions —
instead of raw dashboards.

**Who it's for:** Merchandising, ops, and finance stakeholders who currently rely on analysts
to manually interpret dashboards.

**Core principle for production-grade build:** treat this like a real internal product from
day one — proper repo structure, environment separation, config management, tests, logging,
and a clear data-handling boundary — not a notebook-style prototype.

---

## 2. Target Architecture (Production-Level)

```
retail-pulse/
├── src/
│   ├── data/              # data access layer — DB connections, query functions
│   ├── analysis/          # aggregation & metric computation (pandas/SQL)
│   ├── narrative/          # Claude API integration for narrative generation
│   ├── api/                # (optional) FastAPI backend if you separate UI from logic
│   └── ui/                  # Streamlit or web frontend
├── tests/
│   ├── unit/
│   └── integration/
├── config/
│   ├── settings.py          # environment-aware config (dev/staging/prod)
│   └── .env.example
├── scripts/                 # one-off / maintenance scripts (e.g. data generation)
├── docs/
│   └── architecture.md
├── .github/
│   └── workflows/           # CI pipeline (lint, test, on every PR)
├── .gitignore
├── requirements.txt / pyproject.toml
├── README.md
└── Dockerfile               # for later real deployment
```

**Key production decisions to make explicit up front (put these in `docs/architecture.md`):**
- Data boundary: raw data never leaves the local/company environment; only aggregated
  summaries are sent to the Claude API
- Config layers: dev (synthetic data), staging (masked/sampled real data, if approved),
  prod (real data, company Anthropic account only)
- Secrets: never in code, never in git — environment variables + `.env` (gitignored) locally,
  a secrets manager in production
- Logging: log what was sent to the API (the aggregated payload) for auditability, never log
  raw records

---

## 3. Build Order & Prompts for Sonnet (Claude Code, local VS Code)

Work through these in order. Each prompt assumes you paste it into Claude Code inside the
relevant project folder, and that it has read access to prior files it created.

### Step 0 — Repo & environment scaffolding
**Prompt:**
> "Set up a production-style Python project called retail-pulse with this structure: src/data,
> src/analysis, src/narrative, src/ui, tests/unit, tests/integration, config, scripts, docs.
> Use pyproject.toml for dependency management, add a .gitignore appropriate for Python +
> secrets + local databases, and add a config/settings.py that loads environment-specific
> settings (dev/staging/prod) from environment variables with sensible dev defaults."

### Step 1 — Synthetic data layer (dev environment)
**Prompt:**
> "In scripts/, write a synthetic data generator matching this schema: txn_hdr (basket-level:
> basket_id, household_id, store_id, day, week, trans_time, total_basket_value), txn_itm
> (UPC-level: basket_id, household_id, store_id, day, upc, quantity, sales_value,
> retail_discount, coupon_discount, promo_flag), upc (upc, department, commodity, brand,
> base_price), store (store_id, region, store_format, size_sqft), lookup_day (day, week,
> calendar_date, holiday_flag, season), household_segmentation (household_id, segment_name,
> income_band, family_size), promo (upc, store_id, week, promo_type, discount_pct). Generate a
> year of realistic data with seasonality, promo lift effects, and at least one planted
> anomaly (e.g. a regional stockout) for testing detection logic later. Save to a local SQLite
> file used only in the dev environment."

### Step 2 — Data access layer
**Prompt:**
> "In src/data/, build a clean data access layer with typed functions for querying each table,
> abstracted so the underlying source (SQLite now, a real warehouse connection later) can be
> swapped without changing calling code. Include connection handling and basic error handling."

### Step 3 — Analysis / metrics engine
**Prompt:**
> "In src/analysis/, write functions that compute: week-over-week sales change by department
> and region, stockout detection (SKUs with sales history that drop to zero in a store),
> promo lift (sales comparison for promo vs non-promo periods), and segment-level basket
> behavior. Each function should return a small structured summary object, not raw rows.
> Add docstrings explaining the business logic for each metric, since this needs to be
> reviewed by someone with retail domain knowledge."

### Step 4 — Narrative layer (Claude API integration)
**Prompt:**
> "In src/narrative/, write a module that takes the structured summary from the analysis layer
> and calls the Claude API to generate a short report: headline, likely cause, and 3
> recommended actions. Load the API key from environment variables only. Add retry/error
> handling. Add a strict guard that raises an error if anything resembling a raw record
> (e.g. a household_id-level list) is passed into the prompt payload — this module should
> only ever accept pre-aggregated summaries."

### Step 5 — UI layer
**Prompt:**
> "In src/ui/, build a Streamlit app that lets a user select a week and region, calls the
> analysis and narrative layers, and displays results as metric cards plus the narrative
> report. Keep business logic out of the UI layer — it should only call functions from
> src/analysis and src/narrative."

### Step 6 — Tests
**Prompt:**
> "In tests/unit/, write pytest tests for the analysis functions against the synthetic
> database, covering the planted anomaly, a normal week, and edge cases (first week with no
> prior data, a week with no promos). In tests/integration/, write a test that runs the full
> pipeline end-to-end on synthetic data and asserts the narrative output contains expected
> key terms without asserting exact wording."

### Step 7 — CI pipeline
**Prompt:**
> "Add a GitHub Actions workflow in .github/workflows/ that runs linting (ruff or flake8) and
> pytest on every push and pull request to main."

### Step 8 — Documentation
**Prompt:**
> "Write README.md (setup instructions, how to run locally, architecture summary) and
> docs/architecture.md (the data flow diagram, the data-boundary rule that raw data never
> reaches the API, and environment/config strategy). Write these assuming a technical
> reviewer who was not involved in the build will read them."

---

## 4. GitHub Workflow

```bash
git init
git add .
git commit -m "chore: project scaffolding"
gh repo create retail-pulse --private --source=. --remote=origin
git push -u origin main
```

Use a feature branch per step above (`feature/data-layer`, `feature/analysis-engine`,
`feature/narrative-layer`, `feature/ui`, `feature/tests`, `feature/ci`), PR into `main`, and
require the CI checks to pass before merge — even solo, this builds the habit and gives you a
clean history to show reviewers.

**Keep the repo private** until explicitly cleared for wider visibility.

---

## 5. Deployment Path

| Stage | Environment | Data | Notes |
|---|---|---|---|
| Dev | Local machine | Synthetic only | Current stage |
| Demo | Streamlit Community Cloud or local demo | Synthetic only | For manager/stakeholder review |
| Staging | Internal server | Masked/sampled real data (if approved) | Requires IT/Security sign-off |
| Production | Internal infra (Docker/internal Streamlit/K8s per company standard) | Real, aggregated-only | Requires formal internal tool approval |

Do not skip stages. Each stage change should be its own explicit decision, not an incidental
side effect of "it worked so I pointed it at real data."

---

## 6. Manager / Senior Review Checklist

- [ ] Architecture doc reviewed — data boundary (raw data never reaches the API) is clearly
      enforced in code, not just described
- [ ] Config/secrets handling reviewed — no keys in code or git history
- [ ] Test coverage reviewed — planted anomaly detection actually passes
- [ ] Sample narrative outputs reviewed for factual accuracy against underlying numbers
- [ ] Repo visibility confirmed private
- [ ] Clear owner and next steps identified for staging/production stages, contingent on
      IT/Security approval

---

## 7. Working Split Going Forward

- **Ideation, architecture, prompt design (this document):** done at this stage
- **Implementation (writing/running/debugging code in VS Code):** Claude Code with Sonnet,
  using the prompts above in order, one step at a time
- **Review/validation:** you and your manager, using the checklist in Section 6
