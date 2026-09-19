# Stock Research Framework — TypeSafe Cookbook

Runs the 14-module equity research framework (see `Stock_Research_Framework_v1.pdf`)
over any stock, given two inputs per company:

1. **A screener.in Excel export** in the "Dr. Vijay Malik Screener Excel Template" shape
   (`Data Sheet` + `Dr Vijay Malik Analysis` tabs). Fully numeric, fully reusable —
   drop in a different company's export and every ratio recomputes automatically.
   No code changes needed.
2. **A qualitative brief JSON** — business description, moat evidence, growth-driver
   evidence, risk narrative, price/sentiment narrative, AI-risk evidence, and
   valuation-scenario assumptions. The Excel has no text in it, and the framework
   itself requires every claim to be evidence-grounded ("every claim must come from
   filings, not third-party summaries") — so this has to be authored per stock.

## Why the split

Numeric/mechanical parts of the framework (financial ratios, ROIC math,
reverse-valuation scenario math) are plain Python arithmetic in `excel_loader.py` —
an LLM adds nothing there, and several of the framework's own guardrails demand
mechanical, non-discretionary application anyway. Qualitative judgment calls (Moat,
Growth Drivers, Risk ratings, Sentiment, AI Risk, the final Reject/Watchlist/Buy
decision) are TypeSafe `Noul`/`Choice`/`Score` calls over the brief's evidence text —
see `stock_research_cookbook.py` for the full module-by-module breakdown.

## Which TypeSafe primitive is used where, and why

10 of the 14 modules call TypeSafe. Across those, all three primitives appear, but
very unevenly — `Choice` does most of the work, `Noul` covers a handful of pure
yes/no checks, and `Score` is used exactly once.

**`Noul` (yes/no probability) — 6 questions, 2 modules**
- Module 02 (Business Analysis): `pricing_power` — does the evidence show the
  company can raise prices without losing customers?
- Module 03 (Moat Analysis): one `present_<source>` question per moat source
  (switching costs, intangible assets, network effects, low-cost production,
  counter-positioning) — is this specific moat genuinely present with concrete
  evidence?

Noul fits these because each is a standalone yes/no judgment with no need to
compare against sibling options.

**`Choice` (pick one of a defined set) — 24 questions, 9 modules — the workhorse**
- Module 02: `revenue_pattern` (Recurring/OneTime/Project-based repeat),
  `recession_behavior` (Cyclical/Resilient/ModeratelyCyclical)
- Module 03: `size` (None/Narrow/Wide), `direction` (Widening/Stable/Narrowing)
- Module 04 (Growth Drivers): one Choice per driver, 7 total — Strong/Moderate/
  Weak/NotApplicable
- Module 06 (Risk): one Choice per dimension, 4 total — Red/Yellow/Green
- Module 08 (Sentiment): `sentiment_tone`, `outlook_12m`
- Module 09 (AI Risk): one Choice per lens, 4 total — Fragile/Robust/AntiFragile
- Module 10 (Balance Sheet): `verdict` — synthesizes the computed ratios into
  VeryStrong/Strong/Adequate/Stressed
- Module 12 (Runway): `runway` — Short/Medium/Long
- Module 14 (Decision): `decision` — Reject/Watchlist/Buy

Choice dominates because almost every judgment in this framework is "which
labeled bucket does this fall into," and Choice's distribution over
mutually-exclusive options is exactly that shape.

**`Score` (probability-weighted position on ordered levels) — 1 question, 1 module**
- Module 11 (Cash Flow): `capital_allocation_grade` — Poor / Below Average /
  Average / Good / Excellent, given computed ROIC, dilution, and self-funding
  evidence.

Score is used exactly once because it's the only place a genuinely continuous
ordinal position (rather than a discrete label) was needed. Notably, it's *not*
used for Growth Drivers even though "Strong/Moderate/Weak" looks ordinal — Choice
was used there instead, since the option set also needs a non-ordinal
"NotApplicable" bucket, which breaks Score's assumption of an ordered scale (see
the comment above `module_04_growth` in `stock_research_cookbook.py`).

## Running it

```bash
.venv\Scripts\python.exe stock_research_cookbook.py "Input\<Company>.xlsx" "Input\<company>_brief.json"
```

Results are cached to `stock_cache.json`, keyed by the exact content of the Excel
figures and brief text passed to each call — a different company or an edited brief
produces a fresh cache entry automatically; nothing needs to be cleared by hand.

On Windows, run with `PYTHONUTF8=1` set (e.g. `PYTHONUTF8=1 .venv\Scripts\python.exe ...`
from Git Bash) — the brief text contains ₹ symbols, and Python's default file/console
encoding on Windows isn't UTF-8 unless this is set.

## Producing a brief JSON for a new stock

Run the prompt below in any capable chat LLM with the company's annual report,
investor presentation, or other filings attached or pasted in. Save its output
exactly as `Input\<company>_brief.json`.

````text
You are preparing a structured evidence brief for a stock research pipeline. You
will be given a company's annual report, investor presentation, or other filings.
Extract ONLY what those filings actually support. Do not use third-party summaries,
analyst opinions as if they were company facts, or invent anything. If the filings
don't support a field, write "Not disclosed in the provided filings" for that field
rather than guessing.

Output a single JSON object with EXACTLY this shape and these keys (no extra keys,
no prose before or after the JSON):

{
  "company_name": "<full legal or trading name as it appears in the filings>",
  "business_description": "<what the company sells, who buys it, how revenue is split
    by segment/geography, and any evidence of pricing power (e.g. margins holding or
    improving through a period of cost inflation or rapid scaling)>",
  "moat_evidence": [
    "<one bullet per piece of evidence, each citing what specifically supports it
      (a certification, a margin comparison to a named peer, a contract term, a
      customer-switching-cost fact, etc.). Cover what you can find across these five
      possible moat sources: Switching Costs, Intangible Assets (brand/patent/licence/
      proprietary data), Network Effects, Low-Cost Production, Counter-Positioning.
      Do not force evidence for a source that has none — omit it instead.>"
  ],
  "growth_driver_evidence": {
    "sales_marketing": "<evidence of sales/marketing investment to win new customers,
      or 'Not disclosed in the provided filings'>",
    "distribution_channels": "<evidence of new distribution channels: online,
      international, partnerships>",
    "geographic_expansion": "<evidence of entry into new geographies or adjacent
      segments>",
    "acquisitions": "<evidence of acquisitions and whether they appear value-accretive>",
    "pricing_power": "<evidence of the ability to raise prices without losing
      customers>",
    "new_products": "<evidence of new products/services aimed at existing customers>",
    "customer_retention": "<evidence on customer retention/repeat-order behavior>"
  },
  "risk_evidence": {
    "concentration": "<customer/revenue concentration facts, e.g. top-N customer
      share, and whether it is rising or falling>",
    "disruption": "<evidence of technology or business-model disruption risk to the
      core product, or evidence the company benefits from an industry shift>",
    "outside_forces": "<exposure to regulation, commodity input costs, forex, interest
      rates, tariffs, and any disclosed hedging or mitigation>",
    "competition": "<named competitors, relative margin/position, and whether
      competitive intensity is rising or falling>"
  },
  "price_sentiment_narrative": "<the 12-month share price narrative if disclosed or
    derivable, analyst/institutional sentiment if disclosed, and the strongest bull
    and bear arguments the filings themselves support>",
  "ai_risk_evidence": {
    "liability": "<how costly an error in the core product/service would be, and
      whether that requires human/physical oversight AI cannot replace>",
    "business_model": "<is revenue seat-based/per-user (at risk from AI productivity
      gains) or usage/unit-based (benefits from AI)? Use ONLY the current reported
      revenue mix, not management's stated AI ambitions>",
    "physical_world": "<does the product require physical hardware, manufacturing, or
      on-site work, or is it purely software/digital?>",
    "network": "<does the company hold proprietary data or a network effect AI would
      need, or does it rely on public information?>"
  },
  "valuation_scenarios": {
    "bear": {"probability": <0-1>, "assumption": "<what has to go wrong>",
      "fy_plus5_pat_cr": <number, PAT in Cr 5 years out>, "exit_pe": <number>},
    "base": {"probability": <0-1>, "assumption": "<the base case path>",
      "fy_plus5_pat_cr": <number>, "exit_pe": <number>},
    "bull": {"probability": <0-1>, "assumption": "<what has to go right>",
      "fy_plus5_pat_cr": <number>, "exit_pe": <number>}
  }
}

Important: `valuation_scenarios` is forward-looking analyst judgment, not something
extractable from historical filings — use your own reasoned 5-year PAT and exit-P/E
assumptions per scenario (grounded in the filings' disclosed growth plans, capacity
expansions, and margin trends), and make sure the three probabilities sum to 1.0.
````

## Known limitations

- `excel_loader.py` computes ratios (ROE, ROCE, ROIC, interest coverage, etc.) with
  standard, clearly-documented formulas from the raw `Data Sheet` figures — these are
  **not guaranteed to match Dr. Vijay Malik's exact proprietary formulas** in the
  `Dr Vijay Malik Analysis` tab, which turned out to hold uncalculated formulas
  (no cached values) in this workbook and so can't be read directly.
- Module 11's red-flag checklist and Module 10's Promoter Quality dimension are
  narrower than the framework's full spec — a screener.in export has no shareholding
  pattern, related-party loan, or contingent-liability data. Add that to the brief
  JSON if you have it and want to extend those modules.
- Module 12's reinvestment-rate estimate can read as artificially low in a year where
  working-capital release makes FCF unusually high relative to NOPAT — it's a
  single-year approximation, not a smoothed multi-year figure.
