# Retail Pulse

Internal tool that turns weekly retail transaction data into an automated, plain-English
analyst report (trends, anomalies, recommended actions).

Status: scaffolding (Step 0). Full setup and architecture docs come in Step 8.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp config/.env.example .env
```

Environment is selected with `RETAIL_PULSE_ENV` (`dev` | `staging` | `prod`); see
`config/settings.py`.
