"""Loader for the per-stock qualitative brief JSON file.

The Excel template (see excel_loader.py) carries only numbers. The framework's
qualitative modules (Business Analysis, Moat, Growth Drivers, Risk narrative,
Price & Sentiment, AI Risk, Reverse Valuation scenarios) need evidence text,
which this brief supplies. See README.md for the prompt used to generate one
from a company's own filings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GROWTH_DRIVERS = (
    "sales_marketing",
    "distribution_channels",
    "geographic_expansion",
    "acquisitions",
    "pricing_power",
    "new_products",
    "customer_retention",
)
RISK_DIMENSIONS = ("concentration", "disruption", "outside_forces", "competition")
AI_RISK_LENSES = ("liability", "business_model", "physical_world", "network")


@dataclass
class Brief:
    company_name: str
    business_description: str
    moat_evidence: list[str]
    growth_driver_evidence: dict[str, str]
    risk_evidence: dict[str, str]
    price_sentiment_narrative: str
    ai_risk_evidence: dict[str, str]
    valuation_scenarios: dict[str, dict]
    ticker: str | None = None  # Yahoo Finance ticker symbol; used only when the Excel export is absent


def load_brief(json_path: str | Path) -> Brief:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))

    required = [
        "company_name",
        "business_description",
        "moat_evidence",
        "growth_driver_evidence",
        "risk_evidence",
        "price_sentiment_narrative",
        "ai_risk_evidence",
        "valuation_scenarios",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Brief {json_path} is missing required field(s): {missing}")

    missing_drivers = [d for d in GROWTH_DRIVERS if d not in data["growth_driver_evidence"]]
    if missing_drivers:
        raise ValueError(f"Brief {json_path} growth_driver_evidence missing: {missing_drivers}")

    missing_risks = [d for d in RISK_DIMENSIONS if d not in data["risk_evidence"]]
    if missing_risks:
        raise ValueError(f"Brief {json_path} risk_evidence missing: {missing_risks}")

    missing_lenses = [d for d in AI_RISK_LENSES if d not in data["ai_risk_evidence"]]
    if missing_lenses:
        raise ValueError(f"Brief {json_path} ai_risk_evidence missing: {missing_lenses}")

    for scenario in ("bear", "base", "bull"):
        if scenario not in data["valuation_scenarios"]:
            raise ValueError(f"Brief {json_path} valuation_scenarios missing: {scenario}")

    return Brief(
        company_name=data["company_name"],
        business_description=data["business_description"],
        moat_evidence=data["moat_evidence"],
        growth_driver_evidence=data["growth_driver_evidence"],
        risk_evidence=data["risk_evidence"],
        price_sentiment_narrative=data["price_sentiment_narrative"],
        ai_risk_evidence=data["ai_risk_evidence"],
        valuation_scenarios=data["valuation_scenarios"],
        ticker=data.get("ticker"),
    )
