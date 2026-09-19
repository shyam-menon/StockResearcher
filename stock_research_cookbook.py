"""Stock Research Framework cookbook — 14 modules over an Excel export + a brief.

Numeric/mechanical modules (financial ratios, ROIC math, reverse-valuation
scenario math) are plain Python, computed from excel_loader.FinancialData.
Qualitative judgment modules (Moat, Growth Drivers, Risk narrative, Sentiment,
AI Risk, final decision) are TypeSafe Noul/Choice/Score calls over the
per-stock brief. See README.md for how to produce a brief for a new stock.

Usage:
    .venv\\Scripts\\python.exe stock_research_cookbook.py \\
        "Input/Shilchar Tech.xlsx" "Input/shilchar_brief.json"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from cooksafe import JsonCache
from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, Score, TypeSafeClient

from brief_schema import Brief, load_brief
from excel_loader import FinancialData, load_financials
from html_report import render_html, _slugify

load_dotenv()

TYPESAFE_MODEL = "jev-1.13.0"
client = TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"], timeout=120.0)
json_cache = JsonCache(Path("stock_cache.json"))


# --------------------------------------------------------------------------
# TypeSafe call plumbing — one batched system_one call per module.
# --------------------------------------------------------------------------

@json_cache
def _call_system_one(state_json: str, questions_json: str) -> dict:
    """Cached, generic system_one call. Args are JSON strings so the cache
    key is content-addressed (a different company/brief -> a different key)
    rather than relying on Python object identity."""
    state = json.loads(state_json)
    question_specs = json.loads(questions_json)
    questions = {}
    for key, spec in question_specs.items():
        if spec["kind"] == "noul":
            questions[key] = Noul(instructions=spec["instructions"])
        elif spec["kind"] == "choice":
            questions[key] = Choice(instructions=spec["instructions"], criteria=spec["criteria"])
        else:
            questions[key] = Score(instructions=spec["instructions"], criteria=spec["criteria"])

    response = client.system_one(state=state, questions=questions, model=TYPESAFE_MODEL)

    results = {}
    for key in questions:
        answer = response.answers[key]
        if isinstance(answer, NoulAnswer):
            results[key] = {"kind": "noul", "p_yes": answer.noul}
        elif isinstance(answer, ChoiceAnswer):
            results[key] = {"kind": "choice", "probabilities": dict(answer.probabilities)}
        else:
            results[key] = {"kind": "score", "score": answer.score}
    return results


def ask(state: dict, questions: dict) -> dict:
    """questions: {key: {"kind": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}}"""
    state_json = json.dumps(state, sort_keys=True, default=str)
    questions_json = json.dumps(questions, sort_keys=True)
    return _call_system_one(state_json, questions_json)


def top_choice(result: dict) -> tuple[str, float]:
    probs = result["probabilities"]
    label = max(probs, key=probs.get)
    return label, probs[label]


def noul_yes(result: dict) -> bool:
    return result["p_yes"] >= 0.5


# --------------------------------------------------------------------------
# Module 01 — Business Phase Analysis (mechanical decision tree, per the
# framework's own guardrail: capital returns are checked BEFORE operating
# income, in this exact order).
# --------------------------------------------------------------------------

PHASE_VALUATION_METHODS = {
    1: {"primary": "Revenue multiple (P/S)", "secondary": "Cash runway", "ignore": ["P/E", "P/FCF"]},
    2: {"primary": "Revenue growth / unit economics (P/S, P/GP)", "secondary": "Rule of 40", "ignore": ["P/E"]},
    3: {"primary": "Forward P/E", "secondary": "PEG", "ignore": ["P/S"]},
    4: {"primary": "Trailing P/E", "secondary": "P/FCF", "ignore": ["P/S"]},
    5: {"primary": "Trailing P/E", "secondary": "Trailing P/FCF", "ignore": ["P/S", "P/GP"]},
    6: {"primary": "P/B or liquidation value", "secondary": "Dividend yield", "ignore": ["P/E", "P/S"]},
}


def module_01_phase(fd: FinancialData) -> dict:
    capital_returns = fd.consecutive_dividend_years() >= 1
    profitable = fd.is_profitable()
    losses_improving = fd.losses_improving() if not profitable else None
    revenue_growing = fd.revenue_growing()

    if capital_returns and profitable:
        phase, name = 5, "Capital Return"
        confidence = "High" if fd.consecutive_dividend_years() >= 5 else "Medium"
    elif profitable and revenue_growing:
        phase, name = 4, "Mature Growth"
        confidence = "High"
    elif profitable and not revenue_growing:
        phase, name = 6, "Decline"
        confidence = "Medium"
    elif not profitable and losses_improving and revenue_growing:
        phase, name = 2, "Hypergrowth"
        confidence = "Medium"
    elif not profitable and revenue_growing:
        phase, name = 3, "Growth"
        confidence = "Medium"
    else:
        phase, name = 1, "Startup"
        confidence = "Low"

    return {
        "phase": phase,
        "phase_name": name,
        "confidence": confidence,
        "capital_returns_years": fd.consecutive_dividend_years(),
        "is_profitable": profitable,
        "revenue_growing": revenue_growing,
    }


# --------------------------------------------------------------------------
# Module 02 — Business Analysis (TypeSafe)
# --------------------------------------------------------------------------

def module_02_business(brief: Brief) -> dict:
    state = {"business_description": brief.business_description}
    questions = {
        "revenue_pattern": {
            "kind": "choice",
            "instructions": "Is the company's revenue recurring/repeat business, or predominantly one-time purchases?",
            "criteria": {
                "Recurring": "Customers buy repeatedly / revenue is subscription- or repeat-order-like.",
                "OneTime": "Each sale is largely a one-off purchase with no built-in repeat cadence.",
                "Project-based repeat": "Individual sales are one-off projects, but the same customers place repeat orders over time.",
            },
        },
        "pricing_power": {
            "kind": "noul",
            "instructions": "Does the business description provide evidence that the company can raise prices without losing customers (e.g. margins held steady or improved through a period of scaling or cost inflation)?",
        },
        "recession_behavior": {
            "kind": "choice",
            "instructions": "Based on the business description, how does this business likely behave in a recession or demand downturn?",
            "criteria": {
                "Cyclical": "Demand closely tracks the broader economic/industrial cycle with no offsetting tailwind.",
                "Resilient": "Demand is largely insulated from the broader economic cycle.",
                "ModeratelyCyclical": "Some cyclicality exists but is meaningfully offset by a structural or policy-driven tailwind.",
            },
        },
    }
    result = ask(state, questions)
    revenue_pattern, _ = top_choice(result["revenue_pattern"])
    recession_behavior, _ = top_choice(result["recession_behavior"])
    return {
        "revenue_pattern": revenue_pattern,
        "has_pricing_power": noul_yes(result["pricing_power"]),
        "recession_behavior": recession_behavior,
    }


# --------------------------------------------------------------------------
# Module 03 — Moat Analysis (TypeSafe)
# --------------------------------------------------------------------------

MOAT_SOURCES = ["switching_costs", "intangible_assets", "network_effects", "low_cost_production", "counter_positioning"]
MOAT_SOURCE_LABELS = {
    "switching_costs": "Switching Costs: do customers face significant cost or friction switching to a competitor?",
    "intangible_assets": "Intangible Assets: does a brand, patent, regulatory licence, or proprietary data provide real pricing power?",
    "network_effects": "Network Effects: does the platform/product become more valuable as more users or customers join?",
    "low_cost_production": "Low-Cost Production: does the company have a cost structure that peers structurally cannot match?",
    "counter_positioning": "Counter-Positioning: is the business model one incumbents cannot copy without destroying their own economics?",
}


def module_03_moat(brief: Brief) -> dict:
    state = {"moat_evidence": brief.moat_evidence}
    questions = {
        f"present_{src}": {
            "kind": "noul",
            "instructions": f"Given the moat evidence, is this moat source genuinely present with concrete supporting evidence (not just a vague claim)? {MOAT_SOURCE_LABELS[src]}",
        }
        for src in MOAT_SOURCES
    } | {
        "size": {
            "kind": "choice",
            "instructions": "Given the moat evidence overall, how large is the company's primary moat?",
            "criteria": {
                "None": "No credible moat source with hard evidence.",
                "Narrow": "At least one moat source with concrete evidence, but not decisive/durable enough to be called wide.",
                "Wide": "Multiple reinforcing moat sources with strong, durable evidence.",
            },
        },
        "direction": {
            "kind": "choice",
            "instructions": "Given the moat evidence, is the moat widening, stable, or narrowing over time?",
            "criteria": {
                "Widening": "Evidence shows the competitive advantage strengthening over time.",
                "Stable": "Evidence shows the competitive advantage holding steady.",
                "Narrowing": "Evidence shows the competitive advantage eroding over time.",
            },
        },
    }
    result = ask(state, questions)
    present = {src: noul_yes(result[f"present_{src}"]) for src in MOAT_SOURCES}
    size, _ = top_choice(result["size"])
    direction, _ = top_choice(result["direction"])
    return {"present": present, "size": size, "direction": direction}


# --------------------------------------------------------------------------
# Module 04 — Growth Drivers (TypeSafe)
# --------------------------------------------------------------------------

GROWTH_DRIVER_LABELS = {
    "sales_marketing": "Sales & marketing investment to win new customers",
    "distribution_channels": "New distribution channels (online, international, partnerships)",
    "geographic_expansion": "Entry into new geographies or adjacent market segments",
    "acquisitions": "Growth through value-accretive acquisitions",
    "pricing_power": "Consistent evidence of pricing power over existing customers",
    "new_products": "New products/services that existing customers will also buy",
    "customer_retention": "Customer retention rate, improving or declining",
}


def module_04_growth(brief: Brief) -> dict:
    state = {"growth_driver_evidence": brief.growth_driver_evidence}
    questions = {
        f"driver_{key}": {
            "kind": "choice",
            "instructions": f"Rate the strength of this growth driver based on the evidence: {label}",
            "criteria": {
                "Strong": "Strong evidence; this is a major, currently-active growth engine.",
                "Moderate": "Some evidence; a secondary contributor, not the primary growth engine.",
                "Weak": "Little to no supporting evidence, or evidence of a headwind.",
                "NotApplicable": "This driver does not apply to this business.",
            },
        }
        for key, label in GROWTH_DRIVER_LABELS.items()
    }
    result = ask(state, questions)
    ratings = {key: top_choice(result[f"driver_{key}"])[0] for key in GROWTH_DRIVER_LABELS}
    strong = [k for k, v in ratings.items() if v == "Strong"]
    return {"ratings": ratings, "primary_drivers": strong}


# --------------------------------------------------------------------------
# Module 05 — Phase Key Metrics (mechanical thresholds, code)
# --------------------------------------------------------------------------

def _bucket(value: float | None, green: float, yellow: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "Red"
    if higher_is_better:
        if value >= green:
            return "Green"
        if value >= yellow:
            return "Yellow"
        return "Red"
    else:
        if value <= green:
            return "Green"
        if value <= yellow:
            return "Yellow"
        return "Red"


def module_05_metrics(fd: FinancialData) -> dict:
    cagr = fd.revenue_cagr(3)
    fcf_ni = fd.fcf_to_net_income()
    interest_ratio = fd.ebit_to_interest()  # None => debt-free
    roic = fd.roic()
    div_years = fd.consecutive_dividend_years()

    metrics = {
        "revenue_cagr_3yr": {"value": cagr, "rating": _bucket(cagr, 0.10, 0.0)},
        "fcf_to_net_income": {"value": fcf_ni, "rating": _bucket(fcf_ni, 0.90, 0.50)},
        "ebit_to_interest": {
            "value": interest_ratio,
            "rating": "Green" if interest_ratio is None else _bucket(interest_ratio, 6.0, 3.0),
            "note": "Debt-free" if interest_ratio is None else None,
        },
        "roic": {"value": roic, "rating": _bucket(roic, 0.20, 0.10)},
        "capital_return_years": {"value": div_years, "rating": _bucket(div_years, 5, 1)},
    }
    green_count = sum(1 for m in metrics.values() if m["rating"] == "Green")
    if green_count >= 4:
        overall = "Strong"
    elif green_count >= 2:
        overall = "Mixed"
    else:
        overall = "Weak"
    return {"metrics": metrics, "overall": overall, "green_count": green_count}


# --------------------------------------------------------------------------
# Module 06 — Risk Analysis (Choice per dimension, code aggregation)
# --------------------------------------------------------------------------

RISK_DIMENSION_LABELS = {
    "concentration": "Customer/revenue concentration — would losing one or two customers seriously hurt the business?",
    "disruption": "Technology or business-model disruption risk to the core product",
    "outside_forces": "Exposure to factors outside the company's control: regulation, commodities, forex, interest rates",
    "competition": "Competitive intensity and whether it is getting better or worse",
}
_RISK_WEIGHT = {"Red": 3, "Yellow": 2, "Green": 1}


def module_06_risk(brief: Brief) -> dict:
    state = {"risk_evidence": brief.risk_evidence}
    questions = {
        f"risk_{key}": {
            "kind": "choice",
            "instructions": f"Rate this risk dimension Red/Yellow/Green based on the evidence: {label}. Default to Yellow if evidence is ambiguous.",
            "criteria": {
                "Red": "Serious, high-severity risk with weak mitigation.",
                "Yellow": "Moderate risk, some mitigation in evidence.",
                "Green": "Low risk with strong mitigation or no material exposure.",
            },
        }
        for key, label in RISK_DIMENSION_LABELS.items()
    }
    result = ask(state, questions)
    ratings = {key: top_choice(result[f"risk_{key}"])[0] for key in RISK_DIMENSION_LABELS}
    avg = sum(_RISK_WEIGHT[r] for r in ratings.values()) / len(ratings)
    if avg >= 2.5:
        overall = "High"
    elif avg >= 1.5:
        overall = "Medium"
    else:
        overall = "Low"
    return {"ratings": ratings, "weighted_average": avg, "overall": overall}


# --------------------------------------------------------------------------
# Module 07 — Valuation Metrics (lookup, code)
# --------------------------------------------------------------------------

def module_07_valuation_metrics(phase_result: dict) -> dict:
    return PHASE_VALUATION_METHODS[phase_result["phase"]]


# --------------------------------------------------------------------------
# Module 08 — Price & Sentiment (TypeSafe)
# --------------------------------------------------------------------------

def module_08_sentiment(brief: Brief, fd: FinancialData) -> dict:
    state = {
        "price_sentiment_narrative": brief.price_sentiment_narrative,
        "current_price": fd.current_price,
    }
    questions = {
        "sentiment_tone": {
            "kind": "choice",
            "instructions": "Based on the narrative, what is the current overall market sentiment tone (analyst/investor/media)?",
            "criteria": {
                "Positive": "Broadly bullish tone and improving positioning.",
                "Neutral": "Mixed or low-conviction tone.",
                "Negative": "Broadly bearish tone and deteriorating positioning.",
            },
        },
        "outlook_12m": {
            "kind": "choice",
            "instructions": "Based on the narrative's bull and bear points, what is the balanced 12-month outlook?",
            "criteria": {
                "Bullish": "Bull case evidence clearly outweighs the bear case.",
                "Neutral": "Bull and bear cases are roughly balanced.",
                "Bearish": "Bear case evidence clearly outweighs the bull case.",
            },
        },
    }
    result = ask(state, questions)
    tone, _ = top_choice(result["sentiment_tone"])
    outlook, _ = top_choice(result["outlook_12m"])
    return {"sentiment_tone": tone, "outlook_12m": outlook}


# --------------------------------------------------------------------------
# Module 09 — AI Risk Assessment (Choice per lens, code override rule)
# --------------------------------------------------------------------------

AI_LENS_LABELS = {
    "liability": "Liability lens: how costly are errors in the core product — does AI hallucination risk matter?",
    "business_model": "Business model lens: does the company charge per user/seat (at risk from AI productivity gains) or per usage/unit (benefits from AI)?",
    "physical_world": "Physical world lens: does the product require physical hardware/infrastructure, or is it purely software?",
    "network": "Network/data lens: does the company own proprietary data/network effects AI needs, or rely on public information?",
}


def module_09_ai_risk(brief: Brief) -> dict:
    state = {"ai_risk_evidence": brief.ai_risk_evidence}
    questions = {
        f"ai_{key}": {
            "kind": "choice",
            "instructions": f"Rate this lens based on the evidence: {label}",
            "criteria": {
                "Fragile": "AI is likely to erode this company's value proposition.",
                "Robust": "Defensible against AI disruption, but not a clear beneficiary.",
                "AntiFragile": "AI structurally strengthens this company's competitive position.",
            },
        }
        for key, label in AI_LENS_LABELS.items()
    }
    result = ask(state, questions)
    ratings = {key: top_choice(result[f"ai_{key}"])[0] for key in AI_LENS_LABELS}

    counts = {"Fragile": 0, "Robust": 0, "AntiFragile": 0}
    for v in ratings.values():
        counts[v] += 1
    if counts["Fragile"] > 0:
        overall = "Fragile"
    elif counts["AntiFragile"] >= 3:
        overall = "Anti-Fragile"
    else:
        overall = "Robust"
    return {"ratings": ratings, "overall": overall}


# --------------------------------------------------------------------------
# Module 10 — Balance Sheet Analysis (ratios in code, Choice verdict)
# --------------------------------------------------------------------------

def module_10_balance_sheet(fd: FinancialData) -> dict:
    net_cash = fd.cash_and_bank[-1] + fd.investments[-1] - fd.debt[-1]
    leverage_rating = "Strong" if fd.is_debt_free() else _bucket(fd.debt_to_equity(), 0.3, 0.7, higher_is_better=False)
    returns_avg = (fd.roe() + fd.roce() + fd.roic()) / 3
    returns_rating = _bucket(returns_avg, 0.20, 0.10)
    dso_now, dso_prev = fd.receivable_days(), fd.receivable_days(-2) if len(fd.sales) > 1 else fd.receivable_days()
    asset_quality_rating = "Weak" if dso_now > dso_prev * 1.2 else "Strong"

    computed = {
        "net_cash_cr": net_cash,
        "leverage_rating": leverage_rating,
        "roe": fd.roe(),
        "roce": fd.roce(),
        "roic": fd.roic(),
        "returns_rating": returns_rating,
        "receivable_days_latest": dso_now,
        "receivable_days_prior": dso_prev,
        "asset_quality_rating": asset_quality_rating,
        "promoter_quality_rating": "Not available (screener export has no shareholding pattern; supply via brief if needed)",
    }

    state = {"balance_sheet_ratios": {k: v for k, v in computed.items() if not isinstance(v, str) or "rating" in k}}
    questions = {
        "verdict": {
            "kind": "choice",
            "instructions": (
                "Given these computed balance sheet ratings and figures, synthesize an overall plain-English "
                "balance sheet strength verdict."
            ),
            "criteria": {
                "VeryStrong": "Net cash, low/no leverage, high returns, and controlled working capital.",
                "Strong": "Financially sound with at most one moderate weak point.",
                "Adequate": "Financially acceptable but with more than one area of concern.",
                "Stressed": "Multiple weak points suggesting financial fragility.",
            },
        }
    }
    result = ask(state, questions)
    verdict, _ = top_choice(result["verdict"])
    computed["verdict"] = verdict
    return computed


# --------------------------------------------------------------------------
# Module 11 — Cash Flow Analysis (ratios/red flags in code, Score grade)
# --------------------------------------------------------------------------

def module_11_cash_flow(fd: FinancialData) -> dict:
    cfo_pat_latest = fd.cfo_to_pat()
    cfo_pat_3yr = fd.cfo_to_pat_avg(3)
    fcf_latest = fd.fcf()

    receivables_growth = (fd.receivables[-1] / fd.receivables[-2] - 1) if len(fd.receivables) > 1 and fd.receivables[-2] else None
    revenue_growth = fd.revenue_growing() and (fd.sales[-1] / fd.sales[-2] - 1) if len(fd.sales) > 1 else None

    red_flags = []
    if receivables_growth is not None and isinstance(revenue_growth, float) and receivables_growth > revenue_growth:
        red_flags.append("Receivables growing faster than revenue")
    if cfo_pat_3yr is not None and cfo_pat_3yr < 0.7:
        red_flags.append(f"3-year average CFO/PAT ({cfo_pat_3yr:.2f}x) below the 0.7x floor")
    if fcf_latest < 0:
        red_flags.append("FCF negative in the latest year")

    # A share-count increase can be a stock split or bonus issue (no dilution at all) rather
    # than fresh equity issuance -- net those out via FinancialData.unexplained_share_increase_pct
    # before treating a share-count rise as dilution evidence. 1% is a materiality floor so
    # routine small ESOP exercises don't swamp the signal.
    max_unexplained_increase = max(
        (fd.unexplained_share_increase_pct(-i) for i in range(1, min(3, len(fd.num_shares) - 1) + 1)),
        default=0.0,
    )
    material_dilution = max_unexplained_increase > 0.01

    state = {
        "capital_allocation_evidence": {
            "roic": fd.roic(),
            "cfo_to_pat_3yr_avg": cfo_pat_3yr,
            "fcf_latest": fcf_latest,
            "unexplained_share_increase_3yr_pct": max_unexplained_increase,
            "material_dilution": material_dilution,
            "is_debt_free": fd.is_debt_free(),
            "red_flags": red_flags,
        }
    }
    questions = {
        "capital_allocation_grade": {
            "kind": "score",
            "instructions": "Grade the quality of this company's capital allocation given the evidence.",
            "criteria": [
                "Poor: value-destroying capital allocation.",
                "Below Average: mixed capital allocation with some value destruction.",
                "Average: capital allocation roughly matches cost of capital.",
                "Good: capital allocation consistently creates value above cost of capital.",
                "Excellent: exceptional ROIC, no dilution, fully self-funded growth.",
            ],
        }
    }
    result = ask(state, questions)
    grade_levels = ["Poor", "Below Average", "Average", "Good", "Excellent"]
    # Score.score is a probability-weighted position (a float), not a level index -- round and clamp.
    grade_index = max(0, min(len(grade_levels) - 1, round(result["capital_allocation_grade"]["score"])))

    return {
        "cfo_to_pat_latest": cfo_pat_latest,
        "cfo_to_pat_3yr_avg": cfo_pat_3yr,
        "fcf_latest": fcf_latest,
        "red_flags": red_flags,
        "capital_allocation_grade": grade_levels[grade_index],
        "note": "Red-flag checklist covers 3 data-driven checks; the framework's full 12-item list also needs "
                "shareholding/related-party data not present in a screener.in export.",
    }


# --------------------------------------------------------------------------
# Module 12 — Incremental ROIC & Runway (arithmetic in code, Choice runway)
# --------------------------------------------------------------------------

def module_12_roic_runway(fd: FinancialData, brief: Brief) -> dict:
    historical_roic = fd.roic()
    years_back = min(3, len(fd.sales) - 1)
    incremental_roic = None
    if years_back > 0:
        nopat_now = fd.ebit[-1] * 0.75
        nopat_then = fd.ebit[-1 - years_back] * 0.75
        ic_now = fd.equity[-1] + fd.debt[-1] - fd.cash_and_bank[-1] - fd.investments[-1]
        ic_then = fd.equity[-1 - years_back] + fd.debt[-1 - years_back] - fd.cash_and_bank[-1 - years_back] - fd.investments[-1 - years_back]
        if ic_now != ic_then:
            incremental_roic = (nopat_now - nopat_then) / (ic_now - ic_then)

    reinvestment_rate = None
    implied_growth = None
    nopat_latest = fd.ebit[-1] * 0.75
    if nopat_latest:
        reinvestment_rate = max(0.0, (nopat_latest - fd.fcf()) / nopat_latest)
        if incremental_roic is not None:
            implied_growth = reinvestment_rate * incremental_roic

    state = {
        "capacity_market_evidence": {
            "new_products": brief.growth_driver_evidence.get("new_products"),
            "geographic_expansion": brief.growth_driver_evidence.get("geographic_expansion"),
        },
        "incremental_roic": incremental_roic,
    }
    questions = {
        "runway": {
            "kind": "choice",
            "instructions": (
                "Given the incremental ROIC and the capacity/market expansion evidence, classify the "
                "reinvestment runway: how many more years can the company plausibly keep reinvesting at "
                "above-cost-of-capital returns?"
            ),
            "criteria": {
                "Short": "Under 3 years — capacity or market headroom is nearly exhausted.",
                "Medium": "3-7 years of visible reinvestment opportunity.",
                "Long": "7-10+ years of visible reinvestment opportunity.",
            },
        }
    }
    result = ask(state, questions)
    runway, _ = top_choice(result["runway"])
    return {
        "historical_roic": historical_roic,
        "incremental_roic_3yr": incremental_roic,
        "reinvestment_rate": reinvestment_rate,
        "implied_growth": implied_growth,
        "actual_revenue_cagr_3yr": fd.revenue_cagr(3),
        "runway": runway,
    }


# --------------------------------------------------------------------------
# Module 13 — Reverse Valuation (mechanical scenario math, code)
# --------------------------------------------------------------------------

def module_13_reverse_valuation(fd: FinancialData, brief: Brief) -> dict:
    current_price = fd.current_price
    shares = fd.num_shares[-1]
    scenarios = {}
    weighted_cagr = 0.0
    for name, s in brief.valuation_scenarios.items():
        future_pat_cr = s["fy_plus5_pat_cr"]
        future_eps = future_pat_cr * 1e7 / shares
        future_price = future_eps * s["exit_pe"]
        cagr = (future_price / current_price) ** (1 / 5) - 1
        scenarios[name] = {"future_price": future_price, "cagr": cagr, "probability": s["probability"]}
        weighted_cagr += s["probability"] * cagr

    base_future_price = scenarios["base"]["future_price"]
    entry_zone = {
        f"{int(target * 100)}pct_cagr": round(base_future_price / (1 + target) ** 5, 2)
        for target in (0.12, 0.15, 0.18)
    }

    hurdle = 0.12
    margin_of_safety = "Low" if weighted_cagr < hurdle + 0.02 else ("Moderate" if weighted_cagr < hurdle + 0.06 else "High")

    return {
        "current_price": current_price,
        "current_pe": fd.pe_ratio(),
        "scenarios": scenarios,
        "probability_weighted_cagr": weighted_cagr,
        "meets_hurdle": weighted_cagr >= hurdle,
        "margin_of_safety": margin_of_safety,
        "entry_zone": entry_zone,
    }


# --------------------------------------------------------------------------
# Module 14 — Investment Decision (Choice given composite scores, code thesis)
# --------------------------------------------------------------------------

def _business_quality_score(moat: dict, growth: dict, risk: dict, ai_risk: dict) -> float:
    moat_points = {"Wide": 3, "Narrow": 2, "None": 0}[moat["size"]]
    growth_points = min(3, len(growth["primary_drivers"]))
    risk_points = {"Low": 3, "Medium": 2, "High": 0}[risk["overall"]]
    ai_points = {"Anti-Fragile": 3, "Robust": 2, "Fragile": 0}[ai_risk["overall"]]
    return round((moat_points + growth_points + risk_points + ai_points) / 12 * 10, 1)


def _financial_quality_score(metrics: dict, balance_sheet: dict, cash_flow: dict) -> float:
    metrics_points = {"Strong": 3, "Mixed": 2, "Weak": 0}[metrics["overall"]]
    bs_points = {"VeryStrong": 3, "Strong": 2, "Adequate": 1, "Stressed": 0}[balance_sheet["verdict"]]
    grade_points = {"Excellent": 3, "Good": 2, "Average": 1, "Below Average": 0, "Poor": 0}[cash_flow["capital_allocation_grade"]]
    return round((metrics_points + bs_points + grade_points) / 9 * 10, 1)


def module_14_decision(
    phase: dict, moat: dict, growth: dict, metrics: dict, risk: dict,
    balance_sheet: dict, cash_flow: dict, roic_runway: dict, valuation: dict, ai_risk: dict,
    company_name: str,
) -> dict:
    business_quality = _business_quality_score(moat, growth, risk, ai_risk)
    financial_quality = _financial_quality_score(metrics, balance_sheet, cash_flow)
    valuation_verdict = "Attractive" if valuation["meets_hurdle"] and valuation["margin_of_safety"] != "Low" else "Not yet attractive"

    state = {
        "business_quality_score_out_of_10": business_quality,
        "financial_quality_score_out_of_10": financial_quality,
        "valuation_verdict": valuation_verdict,
        "probability_weighted_cagr": valuation["probability_weighted_cagr"],
        "margin_of_safety": valuation["margin_of_safety"],
    }
    questions = {
        "decision": {
            "kind": "choice",
            "instructions": (
                "Given the business quality score, financial quality score, and valuation verdict, make the "
                "final call. All three conditions (business quality, financial quality, valuation) must be "
                "acceptable simultaneously for a Buy."
            ),
            "criteria": {
                "Reject": "Business quality or financial quality is unacceptable.",
                "Watchlist": "Business and financial quality are good, but valuation is not yet attractive.",
                "Buy": "Business quality, financial quality, and valuation are all acceptable simultaneously.",
            },
        }
    }
    result = ask(state, questions)
    decision, _ = top_choice(result["decision"])

    kill_criteria = [
        f"Incremental ROIC falls below the ~12% cost-of-capital floor (currently "
        f"{roic_runway['incremental_roic_3yr']:.0%})" if roic_runway["incremental_roic_3yr"] else
        "Incremental ROIC data unavailable — monitor once computable",
        f"Receivable days rise materially above the current {balance_sheet['receivable_days_latest']:.0f} days "
        f"for two consecutive years",
        f"CFO/PAT 3-year average stays below 0.7x (currently "
        f"{cash_flow['cfo_to_pat_3yr_avg']:.2f}x)" if cash_flow["cfo_to_pat_3yr_avg"] else
        "CFO/PAT data unavailable — monitor once computable",
    ]

    one_line_thesis = (
        f"{company_name} is a Phase {phase['phase']} ({phase['phase_name']}) business with a "
        f"{moat['size']}/{moat['direction']} moat and {risk['overall']}-risk profile, offering a "
        f"{valuation['probability_weighted_cagr']:.1%} probability-weighted base CAGR at "
        f"₹{valuation['current_price']:.0f} — verdict: {decision}, with {valuation['margin_of_safety']} margin of safety."
    )

    return {
        "business_quality": business_quality,
        "financial_quality": financial_quality,
        "valuation_verdict": valuation_verdict,
        "decision": decision,
        "kill_criteria": kill_criteria,
        "one_line_thesis": one_line_thesis,
    }


# --------------------------------------------------------------------------
# Report printing + orchestration
# --------------------------------------------------------------------------

def _section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main(xlsx_path: str, brief_path: str) -> None:
    fd = load_financials(xlsx_path)
    brief = load_brief(brief_path)
    company = fd.company_name

    print(f"STOCK RESEARCH FRAMEWORK — {company}")
    print(f"Latest fiscal year end: {fd.latest_year:%Y-%m-%d}  |  CMP: {fd.current_price:,.2f}  |  "
          f"Market cap: {fd.market_cap:,.2f} Cr")

    _section("Module 01 — Business Phase Analysis")
    phase = module_01_phase(fd)
    print(f"Phase {phase['phase']}: {phase['phase_name']}  (confidence: {phase['confidence']})")
    print(f"Profitable: {phase['is_profitable']}  |  Revenue growing: {phase['revenue_growing']}  |  "
          f"Consecutive dividend years: {phase['capital_returns_years']}")

    _section("Module 02 — Business Analysis")
    business = module_02_business(brief)
    print(f"Revenue pattern: {business['revenue_pattern']}  |  Pricing power evidenced: {business['has_pricing_power']}  |  "
          f"Recession behavior: {business['recession_behavior']}")

    _section("Module 03 — Moat Analysis")
    moat = module_03_moat(brief)
    for src, present in moat["present"].items():
        print(f"  {src}: {'present' if present else 'absent'}")
    print(f"Overall moat: {moat['size']}, {moat['direction']}")

    _section("Module 04 — Growth Drivers")
    growth = module_04_growth(brief)
    for driver, rating in growth["ratings"].items():
        print(f"  {driver}: {rating}")
    print(f"Primary (Strong) drivers: {growth['primary_drivers']}")

    _section("Module 05 — Phase Key Metrics")
    metrics = module_05_metrics(fd)
    for name, m in metrics["metrics"].items():
        val = m["value"]
        val_str = f"{val:.1%}" if isinstance(val, float) else str(val)
        print(f"  {name}: {val_str} -> {m['rating']}" + (f" ({m['note']})" if m.get("note") else ""))
    print(f"Overall: {metrics['overall']} ({metrics['green_count']}/5 Green)")

    _section("Module 06 — Risk Analysis")
    risk = module_06_risk(brief)
    for dim, rating in risk["ratings"].items():
        print(f"  {dim}: {rating}")
    print(f"Weighted average: {risk['weighted_average']:.2f} -> Overall risk: {risk['overall']}")

    _section("Module 07 — Valuation Metrics")
    val_metrics = module_07_valuation_metrics(phase)
    print(f"Primary: {val_metrics['primary']}  |  Secondary: {val_metrics['secondary']}  |  "
          f"Ignore: {val_metrics['ignore']}")

    _section("Module 08 — Price & Sentiment")
    sentiment = module_08_sentiment(brief, fd)
    print(f"Sentiment tone: {sentiment['sentiment_tone']}  |  12-month outlook: {sentiment['outlook_12m']}")

    _section("Module 09 — AI Risk Assessment")
    ai_risk = module_09_ai_risk(brief)
    for lens, rating in ai_risk["ratings"].items():
        print(f"  {lens}: {rating}")
    print(f"Overall: {ai_risk['overall']}")

    _section("Module 10 — Balance Sheet Analysis")
    balance_sheet = module_10_balance_sheet(fd)
    print(f"Net cash: {balance_sheet['net_cash_cr']:,.2f} Cr  |  Leverage: {balance_sheet['leverage_rating']}")
    print(f"ROE: {balance_sheet['roe']:.1%}  ROCE: {balance_sheet['roce']:.1%}  ROIC: {balance_sheet['roic']:.1%} "
          f"-> Returns: {balance_sheet['returns_rating']}")
    print(f"Receivable days: {balance_sheet['receivable_days_prior']:.0f} -> {balance_sheet['receivable_days_latest']:.0f} "
          f"-> Asset quality: {balance_sheet['asset_quality_rating']}")
    print(f"Promoter quality: {balance_sheet['promoter_quality_rating']}")
    print(f"Verdict: {balance_sheet['verdict']}")

    _section("Module 11 — Cash Flow Analysis")
    cash_flow = module_11_cash_flow(fd)
    print(f"CFO/PAT (latest): {cash_flow['cfo_to_pat_latest']:.2f}x  |  3yr avg: {cash_flow['cfo_to_pat_3yr_avg']:.2f}x")
    print(f"FCF (latest): {cash_flow['fcf_latest']:,.2f} Cr")
    print(f"Red flags: {cash_flow['red_flags'] or 'None'}")
    print(f"Capital allocation grade: {cash_flow['capital_allocation_grade']}")
    print(f"Note: {cash_flow['note']}")

    _section("Module 12 — Incremental ROIC & Runway")
    roic_runway = module_12_roic_runway(fd, brief)
    print(f"Historical ROIC: {roic_runway['historical_roic']:.1%}")
    if roic_runway["incremental_roic_3yr"] is not None:
        print(f"Incremental ROIC (3yr): {roic_runway['incremental_roic_3yr']:.1%}")
    if roic_runway["implied_growth"] is not None:
        print(f"Reinvestment rate: {roic_runway['reinvestment_rate']:.1%}  |  Implied growth: "
              f"{roic_runway['implied_growth']:.1%}  vs actual 3yr revenue CAGR: "
              f"{roic_runway['actual_revenue_cagr_3yr']:.1%}")
    print(f"Runway: {roic_runway['runway']}")

    _section("Module 13 — Reverse Valuation")
    valuation = module_13_reverse_valuation(fd, brief)
    print(f"Current price: {valuation['current_price']:,.2f}  |  Current P/E: {valuation['current_pe']:.1f}x")
    for name, s in valuation["scenarios"].items():
        print(f"  {name.capitalize()} (p={s['probability']:.0%}): target price {s['future_price']:,.0f} "
              f"-> CAGR {s['cagr']:.1%}")
    print(f"Probability-weighted CAGR: {valuation['probability_weighted_cagr']:.1%} "
          f"(meets 12% hurdle: {valuation['meets_hurdle']})  |  Margin of safety: {valuation['margin_of_safety']}")
    print(f"Entry zone: {valuation['entry_zone']}")

    _section("Module 14 — Investment Decision")
    decision = module_14_decision(
        phase, moat, growth, metrics, risk, balance_sheet, cash_flow, roic_runway, valuation, ai_risk, company,
    )
    print(f"Business Quality: {decision['business_quality']}/10  |  Financial Quality: "
          f"{decision['financial_quality']}/10  |  Valuation: {decision['valuation_verdict']}")
    print(f"DECISION: {decision['decision']}")
    print("Kill criteria:")
    for kc in decision["kill_criteria"]:
        print(f"  - {kc}")
    print(f"\nOne-line thesis: {decision['one_line_thesis']}")

    # Mirror the input side's per-stock folder (Input/<Company>/...) on the output
    # side (Output/<Company>/...), whatever that folder happens to be named.
    company_folder = Path(xlsx_path).resolve().parent.name
    out_dir = Path("Output") / company_folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slugify(company)}_report.html"
    out_path.write_text(
        render_html(
            company, fd, phase, business, moat, growth, metrics, risk, val_metrics,
            sentiment, ai_risk, balance_sheet, cash_flow, roic_runway, valuation, decision,
        ),
        encoding="utf-8",
    )
    print(f"\nHTML report written to: {out_path.resolve()}")


if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "Input/Shilchar/Shilchar Tech.xlsx"
    brief_file = sys.argv[2] if len(sys.argv) > 2 else "Input/Shilchar/shilchar_brief.json"
    main(xlsx, brief_file)
