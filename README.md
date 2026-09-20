# Retail Pulse

**Turn weekly retail transactions into a plain-English analyst report: what changed, the likely
cause, and three recommended actions, instead of another dashboard.**

Retail Pulse computes four retail metrics from transaction data (week-over-week sales, suspected
stockouts, promo lift, and household-segment basket behavior), then has a report engine write a
short summary of them. It is built like a real internal product: layered code, environment-aware
config, an enforced data-privacy boundary, 198 automated tests, and CI.

> **Status:** a development build on **synthetic data**. It has not been connected to real data.

## Sample output

Week 31, West region (synthetic data with a planted Beverages stockout). Written by the free
local model, `Qwen2.5-1.5B-Instruct`, running on a laptop CPU:

> **Headline:** Stockouts Inferred from Zero Sales: 8 Products in 6 Stores in West, Risking About $807 Weekly Sales
>
> **Likely cause:** The most likely explanation is that these products (Beverages/Soda, Beverage/Juice, and Beverage/Water) were unavailable due to stockouts.
>
> **Actions:** 1. Verify stock levels for these products across all stores in West. 2. Replenish these products immediately to avoid further loss of potential sales. 3. Investigate the largest sales decline among the affected products.

The small local model gets this planted case right but can make unsupported statements on
ordinary weeks, so treat its output as a draft. Claude is supported as the production engine.

## What makes it interesting

- **Raw data never leaves the machine.** Only pre-aggregated summaries reach a report engine, and a
  guard enforces that in code, before any model is loaded or any API is called. It rejects
  household-level lists, identifier-like fields, DataFrames and oversized payloads, including
  attempts to hide them inside an otherwise valid summary.
- **Works without an API key.** With no `ANTHROPIC_API_KEY` it uses a free local Hugging Face model;
  with a key it uses Claude. The engine is pluggable.
- **Detection tested against a known answer.** The synthetic data plants a regional stockout and a
  promo-free week; the tests assert the detector finds the first and stays quiet elsewhere.
- **Tests that can fail.** During development the code was deliberately broken nine ways to confirm
  the tests catch each break.
- **Environment-aware and fail-fast.** dev / staging / prod come from environment variables; staging
  and prod refuse to start rather than fall back to the synthetic dev database. Secrets are masked
  in logs.

## How it works

```
database -> data layer -> analysis -> aggregated summaries -> guard -> report engine -> report
 (SQLite)   (row-level)   (metrics)   (a few KB of totals)             Claude API or     (headline,
                                                                       local HF model    cause, 3 actions)
```

| Layer | Folder (in `retail-pulse/src/`) | Job |
|---|---|---|
| Data | `data/` | Typed, read-only queries behind a swappable source (SQLite now, a warehouse later) |
| Analysis | `analysis/` | The four metrics, each returning a small summary object |
| Narrative | `narrative/` | Data-boundary guard and the pluggable report engines |
| UI | `ui/` | Streamlit app: pick a week and region, see metric cards and the report |

## Run it locally

Requires Python 3.10+.

```bash
cd retail-pulse
pip install -e ".[dev]"
pip install -e ".[hf]"                       # optional: the free local report engine (large)
python scripts/generate_synthetic_data.py    # creates a local synthetic database (~20 s)
streamlit run src/ui/app.py                  # opens http://localhost:8501
```

In the app, choose **Week 31** and region **West** to see the planted anomaly, then click
**Generate analyst report**. Run the tests with `pytest` (about 40 seconds, no network or API key
needed) and lint with `ruff check .`.

## Documentation

| | |
|---|---|
| [`retail-pulse/README.md`](retail-pulse/README.md) | Setup, configuration variables, report engines, tests, project layout |
| [`retail-pulse/docs/architecture.md`](retail-pulse/docs/architecture.md) | Data-flow diagram, the data-boundary rule, metric definitions, environment strategy, design decisions, known limitations |
| [`Retail_Pulse_Setup_Guide.md`](Retail_Pulse_Setup_Guide.md) | The original build blueprint this project follows |
| [`CLAUDE.md`](CLAUDE.md) | Working rules for AI-assisted development in this repo |

## Known limitations

Synthetic data only; the stockout thresholds were tuned on it and need re-checking on real volumes.
Stockouts are inferred from sales because there is no inventory data. The local model is a weaker
writer than Claude. Only a SQLite data source exists. The architecture document lists these and
more in full.
