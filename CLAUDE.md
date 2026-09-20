# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

**Retail Pulse** turns weekly retail transaction data into a short plain-English analyst report
(headline, likely cause, 3 recommended actions). The code lives in `retail-pulse/`; the original
blueprint is `Retail_Pulse_Setup_Guide.md` (repo root). Read `retail-pulse/README.md` for setup and
`retail-pulse/docs/architecture.md` for the design. Currently a **dev build on synthetic data only**.

## Commands (run from `retail-pulse/`)

```bash
pip install -e ".[dev]"                          # add ".[hf]" for the free local report engine
python scripts/generate_synthetic_data.py        # create local_dev.db (gitignored, ~20 s)
streamlit run src/ui/app.py                      # the app, http://localhost:8501
pytest                                           # ~200 tests, ~40 s, no network or API key needed
ruff check .                                     # lint (line length 120)
pytest -m live                                   # real Claude call; needs ANTHROPIC_API_KEY, costs money
RETAIL_PULSE_TEST_LOCAL_MODEL=1 pytest -m local_model   # real local model, ~1 min, needs .[hf]
```

## Architecture rules (do not break these)

- **Data boundary: raw records never reach a report engine (Claude or the local model). Only
  pre-aggregated summaries do.** The guard in `src/narrative/guard.py` enforces it before any
  provider is created or model loaded. Loosening the guard, or adding a summary type to
  `ALLOWED_SUMMARY_TYPES`, is a security-relevant change: say so and explain why.
- Layers point one way: `ui -> narrative -> analysis -> data`. `src/ui` may import only
  `src.analysis`, `src.narrative` and `config` (a test enforces it). Business logic stays out of the UI.
- Analysis functions return small frozen summary dataclasses, never DataFrames or row lists.
- Config comes only from environment variables (`config/settings.py`). Staging/prod fail fast if
  required variables are missing; never let them fall back to the dev database.
- **Ask the user before changing the target architecture** in `Retail_Pulse_Setup_Guide.md`
  (folders, layers, config strategy). Explain the change first, then make it.

## Secrets and personal information

- Never commit `.env`, API keys, tokens, database files, CSVs or personal data. `.gitignore`
  covers these at the repo root and in `retail-pulse/`; `config/.env.example` holds blanks only.
- Never print or log a key or a database password (`Settings.__repr__` masks them).
- Commits use the GitHub noreply address, not a personal email. Do not put emails or local
  machine paths in code, docs or tests.

## Testing conventions

- Tests build their own seeded synthetic database in a temp folder (`tests/conftest.py`); they never
  use `local_dev.db`. The generator plants known anomalies (West Beverages stockout, weeks 30 to 33;
  promo-free week 20) and writes an answer key that tests assert against.
- A fixture blocks loading a real Hugging Face model. Never let a normal test download or run one;
  use a fake pipeline, or mark the test `@pytest.mark.local_model`.
- New behavior needs a test that can fail. When adding detection logic, break it on purpose once to
  confirm a test catches it.
- CI (`.github/workflows/ci.yml`, at the git root) runs `ruff check` and `pytest` on Python 3.10
  and 3.12 without PyTorch, so tests must not import `torch` or `transformers` at module level.

## Report engines

`RETAIL_PULSE_NARRATIVE_PROVIDER` = `auto` | `claude` | `huggingface`. `auto` uses Claude when
`ANTHROPIC_API_KEY` is set, otherwise the local model in dev. The local model
(`Qwen/Qwen2.5-1.5B-Instruct`, CPU, ~1 min per report) is a draft-writer: it gets the planted
anomaly right but can state unsupported things on ordinary weeks. Do not present its output as
verified analysis.

## Working conventions

- Windows machine, git `autocrlf` on: working files may be CRLF. When editing files with scripts,
  preserve each file's line endings; prefer the Edit tool for multi-line changes.
- Branches: work on `developer`; `master` gets merged work only after CI passes. One commit per
  logical step, messages like `feat: ...`, `test: ...`, `docs: ...`, `ci: ...`.
- Do not commit or push unless asked. Before any push, scan the diff and history for secrets.
- Style: match the surrounding code; comments explain why, not what; ruff must pass.

## Known gaps

Real Claude call and Python 3.10 are untested; only a SQLite backend exists (a warehouse needs a
new `DataSource`); stockout thresholds were tuned on synthetic data; small groups are not suppressed
in summaries. See `docs/architecture.md`, section 10.
