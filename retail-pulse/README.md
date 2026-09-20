# Retail Pulse

Retail Pulse turns weekly retail transaction data into a short, plain-English analyst report:
what changed, the likely cause, and three recommended actions. It is meant for merchandising,
operations and finance stakeholders who today depend on an analyst to interpret dashboards.

**Status: development build on synthetic data.** Everything below runs locally with no real
data. The written report needs a report engine: the Claude API (needs a key), or a **free local
Hugging Face model** that needs no key (see [Report engines](#report-engines)). What is and is not
verified is listed [below](#what-has-and-has-not-been-verified).

The central design rule: **raw transaction data never leaves the local environment. Only
pre-aggregated summaries ever reach a report engine** (Claude or the local model), and this is
enforced in code, not just described. Details in [docs/architecture.md](docs/architecture.md).

## How it works

```
database  ->  data layer  ->  analysis  ->  aggregated summaries  ->  guard  ->  report engine  ->  report
 (SQLite)    (row-level)    (metrics)      (a few KB of totals)     (enforces     Claude API or      (headline,
                                                                     the boundary) local HF model     cause, 3 actions)
```

| Layer | Folder | Responsibility |
|---|---|---|
| Data | `src/data/` | Typed read-only queries per table behind a swappable `DataSource` (SQLite now, a warehouse later) |
| Analysis | `src/analysis/` | Four metrics, each returning a small summary object: week-over-week sales, stockout detection, promo lift, segment basket behavior |
| Narrative | `src/narrative/` | The only code that writes reports. Guards the boundary, then hands the aggregates to a pluggable engine (Claude API or a local Hugging Face model); validates the report, retries |
| UI | `src/ui/` | Streamlit app: pick a week and region, see metric cards and the report. Presentation only |
| Config | `config/` | Environment-aware settings (dev / staging / prod) from environment variables |

## Setup

Requires Python 3.10 or newer. Run every command from this folder (`retail-pulse/`).

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install -e ".[hf]"               # optional: free local report engine (PyTorch, large)
cp config/.env.example .env          # Windows: copy config\.env.example .env
```

`.env` is gitignored. In dev you do not need to edit it.

## Run locally

```bash
# 1. Create the synthetic dev database (about 20 seconds, deterministic)
python scripts/generate_synthetic_data.py

# 2. Start the app
streamlit run src/ui/app.py
```

The app opens with metric cards for the latest week. To see the planted anomaly, choose
**Week 31** and region **West**: sales fall about 20% and eight Beverages SKUs are flagged as
suspected stockouts.

Click **Generate analyst report** to write the report; the page shows which engine will do it.

### Report engines

| Engine | When it is used | Needs | Notes |
|---|---|---|---|
| **Local Hugging Face model** | Default in dev when no `ANTHROPIC_API_KEY` is set | `pip install -e ".[hf]"`; no key, no account | Runs on your CPU. First use downloads the model (about 3 GB, once). Roughly a minute per report. Nothing leaves the machine |
| **Claude API** | When `ANTHROPIC_API_KEY` is set, and the default in staging/prod | An Anthropic API key | Each report is one paid API call |

Force one with `RETAIL_PULSE_NARRATIVE_PROVIDER=claude` or `huggingface`. The default local model
is `Qwen/Qwen2.5-1.5B-Instruct`; set `RETAIL_PULSE_HF_MODEL` to use another (a larger one writes
better reports but is slower and needs more memory).

**Be aware of the local model's limits.** A 1.5B-parameter model is a capable draft-writer, not an
analyst. On the planted anomaly (Week 31, West) it correctly reports the suspected Beverages
stockouts and recommends verifying and replenishing stock. On an ordinary week it can state things
the numbers do not support (for example hinting at availability problems when none were flagged, or
saying a category fell when it rose). Always check its statements against the metric cards. For
stakeholder-facing reports use Claude or a larger model.

### Configuration

All settings come from environment variables (or `.env` locally). Nothing is hardcoded.

| Variable | Default | Purpose |
|---|---|---|
| `RETAIL_PULSE_ENV` | `dev` | `dev`, `staging` or `prod` |
| `RETAIL_PULSE_DB_URL` | `sqlite:///./local_dev.db` in dev; **required** elsewhere | Data source |
| `RETAIL_PULSE_NARRATIVE_PROVIDER` | `auto` | `auto`, `claude` or `huggingface`. `auto` = Claude if a key is set, else the local model (dev only) |
| `ANTHROPIC_API_KEY` | none; **required** in staging/prod unless the provider is `huggingface` | Claude API key. Never commit it |
| `RETAIL_PULSE_MODEL` | `claude-sonnet-5` | Claude model used when the engine is Claude |
| `RETAIL_PULSE_HF_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` | Hugging Face model used when the engine is local |
| `RETAIL_PULSE_LOG_LEVEL` | `DEBUG` dev / `INFO` staging / `WARNING` prod | Logging verbosity |

Staging and prod refuse to start if the database URL or API key is missing, so a misconfigured
deployment cannot silently fall back to the synthetic dev database. See
[docs/architecture.md](docs/architecture.md#5-environment-and-configuration-strategy).

## Tests and linting

```bash
pytest          # 198 pass in about 40 seconds; 2 opt-in tests (real Claude / real local model) are skipped
ruff check .    # lint
```

The test suite builds its own seeded synthetic database in a temp folder, so it needs no
`local_dev.db`, no network and no API key. It checks the analysis functions against a planted
answer key (a regional stockout in weeks 30 to 33 and a promo-free week 20), the data-boundary
guard, the retry and error handling, the full pipeline with a stubbed report engine, and the
Streamlit app. Two opt-in tests use a real engine:

```bash
pytest -m live                                          # real Claude; needs ANTHROPIC_API_KEY (costs money)
RETAIL_PULSE_TEST_LOCAL_MODEL=1 pytest -m local_model   # real local model; needs .[hf], about a minute
```

The normal suite can never load a real model by accident: a fixture blocks it.

CI (`.github/workflows/ci.yml`, at the git root) runs ruff and pytest on Python 3.10 and 3.12
for every push and pull request.

## Project layout

```
retail-pulse/
  config/          settings.py (dev/staging/prod), .env.example
  src/
    data/          DataSource interface, SQLite implementation, RetailRepository, errors
    analysis/      sales.py, stockouts.py, promo.py, segments.py, models.py, service.py
    narrative/     guard.py, generator.py, providers.py, facts.py, prompts.py, models.py, errors.py
    ui/            app.py (Streamlit)
  scripts/         generate_synthetic_data.py
  tests/           unit/, integration/, conftest.py, fakes.py
  docs/            architecture.md
  pyproject.toml   dependencies, ruff and pytest configuration
```

## What has and has not been verified

**Verified:** the analysis functions against a known planted anomaly; the guard against
row-level data (including attempts to smuggle it inside a valid summary); retry and error
paths; the full pipeline and the UI, using stand-ins for the report engines; lint and tests in a
clean environment on Python 3.11. **The local Hugging Face engine has been run for real** on this
build's hardware (Windows, CPU only): it wrote correct reports for the planted anomaly, and
showed the accuracy limits described above on an ordinary week.

**Not yet verified:**
- **A real Claude call.** The request has only been exercised against a test double. The
  `live` test exists for this and has not been run.
- **Python 3.10 and the GitHub Actions run itself.** CI is configured but has not yet run on GitHub.
- **Real data.** Only synthetic data has been used. The stockout threshold in particular was tuned
  on synthetic data and must be re-checked against real volumes.
- **Staging and production.** Only a SQLite backend exists. A warehouse needs a new `DataSource`
  implementation and IT/Security approval before any real data is connected.

## Further reading

- [docs/architecture.md](docs/architecture.md): data flow, the data-boundary rule, metric
  definitions, environment strategy, design decisions and known limitations.
- `Retail_Pulse_Setup_Guide.md` (one folder up): the original blueprint this build follows.
