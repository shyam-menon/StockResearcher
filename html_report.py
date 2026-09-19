"""Renders the 14-module stock research results as a single local HTML file."""

from __future__ import annotations

import html
import re

_BADGE_CLASS = {
    "Green": "good", "Strong": "good", "Wide": "good", "Widening": "good",
    "AntiFragile": "good", "Anti-Fragile": "good", "Positive": "good", "Bullish": "good",
    "VeryStrong": "good", "Excellent": "good", "Good": "good", "Buy": "good",
    "Yellow": "warn", "Mixed": "warn", "Narrow": "warn", "Stable": "warn",
    "Robust": "warn", "Neutral": "warn", "Adequate": "warn", "Average": "warn",
    "Medium": "warn", "Watchlist": "warn", "Moderate": "warn",
    "Red": "bad", "Weak": "bad", "None": "bad", "Narrowing": "bad",
    "Fragile": "bad", "Negative": "bad", "Bearish": "bad", "Stressed": "bad",
    "Poor": "bad", "Below Average": "bad", "High": "bad", "Reject": "bad",
    "NotApplicable": "muted",
}


def _badge(value) -> str:
    text = str(value)
    cls = _BADGE_CLASS.get(text, "muted")
    return f'<span class="badge {cls}">{html.escape(text)}</span>'


def _badge_as(value, mapping: dict[str, str]) -> str:
    """Like _badge, but with an explicit value->class map — for words like "Low"/"High"
    whose color meaning flips by context (Low risk is good; Low margin of safety is bad)."""
    text = str(value)
    cls = mapping.get(text, "muted")
    return f'<span class="badge {cls}">{html.escape(text)}</span>'


def _fmt(value) -> str:
    if value is None:
        return "&mdash;"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return html.escape(str(value))


def _pct(value) -> str:
    return "&mdash;" if value is None else f"{value:.1%}"


def _title_case(key: str) -> str:
    return key.replace("_", " ").title()


def _table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="kv">{body}</table>'


def _list(items: list[str]) -> str:
    return "<ul class='flags'>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>" if items else "<span class='note'>None</span>"


def _section(title: str, rows: list[tuple[str, str]], extra: str = "") -> tuple[str, str]:
    return title, _table(rows) + extra


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "company"


def render_html(
    company: str, fd, phase, business, moat, growth, metrics, risk, val_metrics,
    sentiment, ai_risk, balance_sheet, cash_flow, roic_runway, valuation, decision,
) -> str:
    sections = [
        _section("01 &middot; Business Phase Analysis", [
            ("Phase", f"{phase['phase']}: {phase['phase_name']}"),
            ("Confidence", _fmt(phase["confidence"])),
            ("Profitable", _fmt(phase["is_profitable"])),
            ("Revenue growing", _fmt(phase["revenue_growing"])),
            ("Consecutive dividend years", _fmt(phase["capital_returns_years"])),
        ]),
        _section("02 &middot; Business Analysis", [
            ("Revenue pattern", _fmt(business["revenue_pattern"])),
            ("Pricing power evidenced", _fmt(business["has_pricing_power"])),
            ("Recession behavior", _fmt(business["recession_behavior"])),
        ]),
        _section(
            "03 &middot; Moat Analysis",
            [(_title_case(src), _badge("Strong" if present else "None")) for src, present in moat["present"].items()]
            + [("Overall size", _badge(moat["size"])), ("Direction", _badge(moat["direction"]))],
        ),
        _section(
            "04 &middot; Growth Drivers",
            [(_title_case(k), _badge(v)) for k, v in growth["ratings"].items()],
            extra=f'<p class="note">Primary drivers: '
                  f'{", ".join(d.replace("_", " ") for d in growth["primary_drivers"]) or "none"}</p>',
        ),
        _section(
            "05 &middot; Phase Key Metrics",
            [
                (_title_case(name), f"{m['value']:.1%} {_badge(m['rating'])}" if isinstance(m["value"], float)
                 else f"{_fmt(m['value'])} {_badge(m['rating'])}")
                for name, m in metrics["metrics"].items()
            ],
            extra=f'<p class="note">Overall: {_badge(metrics["overall"])} ({metrics["green_count"]}/5 Green)</p>',
        ),
        _section(
            "06 &middot; Risk Analysis",
            [(_title_case(k), _badge(v)) for k, v in risk["ratings"].items()]
            + [
                ("Weighted average", f"{risk['weighted_average']:.2f}"),
                ("Overall risk", _badge_as(risk["overall"], {"Low": "good", "Medium": "warn", "High": "bad"})),
            ],
        ),
        _section("07 &middot; Valuation Metrics", [
            ("Primary", _fmt(val_metrics["primary"])),
            ("Secondary", _fmt(val_metrics["secondary"])),
            ("Ignore", _fmt(", ".join(val_metrics["ignore"]))),
        ]),
        _section("08 &middot; Price &amp; Sentiment", [
            ("Sentiment tone", _badge(sentiment["sentiment_tone"])),
            ("12-month outlook", _badge(sentiment["outlook_12m"])),
        ]),
        _section(
            "09 &middot; AI Risk Assessment",
            [(_title_case(k), _badge(v)) for k, v in ai_risk["ratings"].items()]
            + [("Overall", _badge(ai_risk["overall"]))],
        ),
        _section("10 &middot; Balance Sheet Analysis", [
            ("Net cash", f"{balance_sheet['net_cash_cr']:,.2f} Cr"),
            ("Leverage", _badge(balance_sheet["leverage_rating"])),
            ("ROE / ROCE / ROIC", f"{balance_sheet['roe']:.1%} / {balance_sheet['roce']:.1%} / {balance_sheet['roic']:.1%}"),
            ("Returns rating", _badge(balance_sheet["returns_rating"])),
            ("Receivable days (prior -> latest)",
             f"{balance_sheet['receivable_days_prior']:.0f} &rarr; {balance_sheet['receivable_days_latest']:.0f}"),
            ("Asset quality", _badge(balance_sheet["asset_quality_rating"])),
            ("Promoter quality", f'<span class="note">{html.escape(balance_sheet["promoter_quality_rating"])}</span>'),
            ("Verdict", _badge(balance_sheet["verdict"])),
        ]),
        _section(
            "11 &middot; Cash Flow Analysis",
            [
                ("CFO/PAT latest / 3yr avg", f"{cash_flow['cfo_to_pat_latest']:.2f}x / {cash_flow['cfo_to_pat_3yr_avg']:.2f}x"),
                ("FCF (latest)", f"{cash_flow['fcf_latest']:,.2f} Cr"),
                ("Red flags", _list(cash_flow["red_flags"])),
                ("Capital allocation grade", _badge(cash_flow["capital_allocation_grade"])),
            ],
            extra=f'<p class="note">{html.escape(cash_flow["note"])}</p>',
        ),
        _section("12 &middot; Incremental ROIC &amp; Runway", [
            ("Historical ROIC", _pct(roic_runway["historical_roic"])),
            ("Incremental ROIC (3yr)", _pct(roic_runway["incremental_roic_3yr"])),
            ("Reinvestment rate", _pct(roic_runway["reinvestment_rate"])),
            ("Implied growth vs actual 3yr CAGR",
             f"{_pct(roic_runway['implied_growth'])} vs {_pct(roic_runway['actual_revenue_cagr_3yr'])}"),
            ("Runway", _badge(roic_runway["runway"])),
        ]),
        _section(
            "13 &middot; Reverse Valuation",
            [("Current price / P/E", f"₹{valuation['current_price']:,.2f} / {valuation['current_pe']:.1f}x")]
            + [
                (f"{name.capitalize()} (p={s['probability']:.0%})", f"target ₹{s['future_price']:,.0f} &rarr; {s['cagr']:.1%} CAGR")
                for name, s in valuation["scenarios"].items()
            ]
            + [
                ("Probability-weighted CAGR",
                 f"{valuation['probability_weighted_cagr']:.1%} (meets 12% hurdle: {_fmt(valuation['meets_hurdle'])})"),
                ("Margin of safety",
                 _badge_as(valuation["margin_of_safety"], {"Low": "bad", "Moderate": "warn", "High": "good"})),
                ("Entry zone", html.escape(", ".join(f"{k.replace('pct_cagr', '%')}: ₹{v:,.0f}" for k, v in valuation["entry_zone"].items()))),
            ],
        ),
        _section("14 &middot; Investment Decision", [
            ("Business Quality", f"{decision['business_quality']}/10"),
            ("Financial Quality", f"{decision['financial_quality']}/10"),
            ("Valuation verdict", _fmt(decision["valuation_verdict"])),
            ("Decision", _badge(decision["decision"])),
            ("Kill criteria", _list(decision["kill_criteria"])),
        ]),
    ]

    section_html = "".join(f"<section><h2>{title}</h2>{body}</section>" for title, body in sections)
    decision_class = _BADGE_CLASS.get(decision["decision"], "muted")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(company)} — Stock Research Report</title>
<style>
  :root {{
    --bg: #f7f7f5; --panel: #ffffff; --ink: #1a1a1a; --muted: #6b6b6b; --border: #e4e4e0;
    --good-bg: #e6f4ea; --good-ink: #1e7a34;
    --warn-bg: #fdf3e0; --warn-ink: #a5670e;
    --bad-bg: #fbe8e7; --bad-ink: #b3261e;
    --muted-bg: #eeeeee; --muted-ink: #555555;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16171a; --panel: #1f2023; --ink: #eaeaea; --muted: #9a9a9a; --border: #333438;
      --good-bg: #163823; --good-ink: #6fd68b;
      --warn-bg: #3a2f14; --warn-ink: #e6b34f;
      --bad-bg: #3a1c1b; --bad-ink: #f08b85;
      --muted-bg: #2a2b2e; --muted-ink: #bdbdbd;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--ink); margin: 0; padding-block: 32px;
    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding-inline: 20px; }}
  header {{ margin-bottom: 24px; }}
  header h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  header .meta {{ color: var(--muted); font-size: 0.95rem; }}
  .thesis {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 18px 20px; margin: 20px 0 28px; font-size: 1.05rem; line-height: 1.5;
  }}
  .thesis .decision-line {{ margin-top: 10px; font-weight: 600; }}
  section {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 20px; margin-bottom: 16px;
  }}
  section h2 {{ font-size: 1rem; margin: 0 0 10px; color: var(--muted); font-weight: 700; letter-spacing: .02em; }}
  table.kv {{ width: 100%; border-collapse: collapse; }}
  table.kv th {{ text-align: left; color: var(--muted); font-weight: 500; padding: 5px 10px 5px 0; vertical-align: top; width: 42%; }}
  table.kv td {{ padding: 5px 0; vertical-align: top; }}
  ul.flags {{ margin: 0; padding-left: 18px; }}
  p.note, span.note {{ color: var(--muted); font-size: 0.9rem; }}
  p.note {{ margin: 8px 0 0; }}
  .badge {{
    display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 0.82rem; font-weight: 600;
  }}
  .badge.good {{ background: var(--good-bg); color: var(--good-ink); }}
  .badge.warn {{ background: var(--warn-bg); color: var(--warn-ink); }}
  .badge.bad {{ background: var(--bad-bg); color: var(--bad-ink); }}
  .badge.muted {{ background: var(--muted-bg); color: var(--muted-ink); }}
  footer {{ color: var(--muted); font-size: 0.8rem; text-align: center; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{html.escape(company)}</h1>
    <div class="meta">Latest fiscal year end: {fd.latest_year:%Y-%m-%d} &middot; CMP: ₹{fd.current_price:,.2f} &middot;
      Market cap: {fd.market_cap:,.2f} Cr</div>
  </header>

  <div class="thesis">
    {html.escape(decision["one_line_thesis"])}
    <div class="decision-line">Decision: <span class="badge {decision_class}">{html.escape(decision["decision"])}</span></div>
  </div>

  {section_html}

  <footer>Generated by stock_research_cookbook.py &mdash; TypeSafe-powered qualitative judgments, plain-code financial arithmetic.</footer>
</div>
</body>
</html>
"""
