"""Prompt text and the output schema for the weekly analyst report."""

from __future__ import annotations

import json
from typing import Any

from src.narrative.facts import build_facts

SYSTEM_PROMPT = """\
You are a retail analyst writing a short weekly report for merchandising, operations and finance \
stakeholders. You are given pre-aggregated metrics as JSON. Use ONLY those figures.

Rules:
- Never invent numbers, stores, products or causes of fact. Every figure you quote must appear \
in the data, exactly as given.
- Percentages named *_pct are already percentages (12.3 means 12.3%). A null value means \
"not available", not zero.
- If has_prior_data, has_history or has_promos is false, say the comparison is unavailable \
rather than guessing.
- The likely cause is your best inference from the data, worded as a hypothesis ("consistent \
with ...", "likely ...") unless the data proves it. Stockouts here are inferred from zero sales, \
not measured inventory.
- Recommend exactly 3 concrete actions a retail team could take this week, most important first.
- Plain English, no jargon, no markdown.

Return JSON with: headline (one sentence, the single most important finding), likely_cause \
(2-3 sentences), recommended_actions (array of exactly 3 short action sentences).\
"""

# Small local models need the output format spelled out with an example, and shorter rules.
LOCAL_SYSTEM_PROMPT = """\
You are a retail analyst writing a short weekly report. You will be given facts. Use ONLY those \
facts and copy numbers exactly as written. Never invent numbers, products or stores.

Reply with ONLY a JSON object, no other text, in exactly this shape:
{"headline": "<one sentence: the most important finding>",
 "likely_cause": "<2 sentences: the most likely explanation, worded as a hypothesis>",
 "recommended_actions": ["<action 1>", "<action 2>", "<action 3>"]}

Rules: exactly 3 recommended actions, each one short and concrete. Stockouts are inferred from \
zero sales, not measured inventory, so say "suspected". If a comparison is unavailable, say so.

How to write it:
- headline: state the change in total sales with its percentage and name the biggest problem. If \
the facts list a MOST IMPORTANT FINDING (suspected stockouts), the headline must mention it.
- likely_cause: if suspected stockouts are listed, say those products (name the department and \
region) sold nothing, so sales likely fell because they were unavailable. Do not blame promotions \
for a sales drop when promotions sold MORE units. If the facts say there are no suspected \
stockouts, do NOT mention stockouts or stock at all; explain the change using the biggest mover.
- recommended_actions: if stockouts are listed: (1) verify stock and replenish those products, \
(2) investigate the largest sales decline, (3) act on promotions or a customer segment. If none \
are listed: (1) investigate the largest sales decline, (2) review promotions, (3) review the \
segment whose average basket changed most.\
"""

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "likely_cause": {"type": "string"},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "likely_cause", "recommended_actions"],
    "additionalProperties": False,
}


def build_user_prompt(payload: dict[str, Any]) -> str:
    """Render the (already guarded) payload into the user message."""
    return "Weekly retail metrics (JSON):\n" + json.dumps(payload, indent=2, sort_keys=True)


def build_local_user_prompt(payload: dict[str, Any]) -> str:
    """Fact-sheet form of the (already guarded) payload for small local models."""
    return "Facts for this week:\n" + build_facts(payload) + "\n\nWrite the JSON report now."
