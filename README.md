# Stock Research Framework — TypeSafe Cookbook

Runs the 14-module equity research framework (see `Stock_Research_Framework_v1.pdf`)
over any stock, given two inputs per company:

1. **A screener.in Excel export** in the "Dr. Vijay Malik Screener Excel Template" shape
   (`Data Sheet` + `Dr Vijay Malik Analysis` tabs). Fully numeric, fully reusable —
   drop in a different company's export and every ratio recomputes automatically.
   No code changes needed. screener.in only covers Indian-listed companies; if the
   Excel export isn't present for a company, the tool automatically falls back to
   fetching financials from Yahoo Finance instead (`online_loader.py`) — see
   "Running it" below.
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
Growth Drivers, Risk ratings, Sentiment, AI Risk) are TypeSafe `Noul`/`Choice`/`Score`
calls over the brief's evidence text — see `stock_research_cookbook.py` for the full
module-by-module breakdown. The final Reject/Watchlist/Buy decision (Module 14) is
deterministic code that combines those judgments' resulting scores against explicit
thresholds, rather than a further Jev call — see "Consistency guardrails on top of
Jev judgments" below for why.

## Which TypeSafe primitive is used where, and why

9 of the 14 modules call TypeSafe. Across those, all three primitives appear, but
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

**`Choice` (pick one of a defined set) — 23 questions, 8 modules — the workhorse**
- Module 02: `revenue_pattern` (Recurring/OneTime/Project-based repeat/Mixed),
  `recession_behavior` (Cyclical/Resilient/ModeratelyCyclical)
- Module 03: `size` (None/Narrow/Wide), `direction` (Widening/Stable/Narrowing)
- Module 04 (Growth Drivers): one Choice per driver, 7 total — Strong/Moderate/
  Weak/NotApplicable/InsufficientEvidence
- Module 06 (Risk): one Choice per dimension, 4 total — Red/Yellow/Green/Unknown
- Module 08 (Sentiment): `sentiment_tone`, `outlook_12m`
- Module 09 (AI Risk): one Choice per lens, 4 total — Fragile/Robust/AntiFragile
- Module 10 (Balance Sheet): `verdict` — synthesizes the computed ratios into
  VeryStrong/Strong/Adequate/Stressed
- Module 12 (Runway): `runway` — Short/Medium/Long

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

## Consistency guardrails on top of Jev judgments

Each Jev call above answers one question in isolation. A few places in the
framework need more than that — either a cross-check between two independently-
asked questions, or a way to say "the evidence doesn't say" without that being
silently treated as a bad answer. These are enforced in code, not left to a
prompt instruction:

- **Module 3 (Moat) — evidence-consistency floor.** The 5 per-source `Noul`
  checks and the overall `size` Choice are asked independently, so nothing
  stops Jev from calling the moat "Wide" while only one source actually came
  back "Present." `_apply_moat_consistency_floor` caps (never raises) the
  verdict to what the source count supports: Wide requires ≥2 sources rated
  Present, Narrow requires ≥1, else the verdict is downgraded. The raw Jev
  verdict is kept as `size_raw` and shown alongside the floored one whenever
  a downgrade happens, so the discrepancy stays visible rather than hidden.
- **Module 9 (AI Risk) — confidence-gated override.** A single lens rated
  Fragile overrides the other three lenses' verdicts — but only if that
  lens's own confidence is ≥`AI_FRAGILE_OVERRIDE_CONFIDENCE` (0.70). A
  Fragile call that's barely ahead of a near-even 3-way split no longer
  flips the whole company.
- **Modules 4 & 6 — insufficient evidence is its own answer.** Growth's
  `Weak` and Risk's old "default to Yellow if ambiguous" instruction both
  conflated "the evidence doesn't address this" with "this is genuinely
  weak/risky." Growth now has a 5th option, `InsufficientEvidence`; Risk now
  has a 4th, `Unknown`. `Unknown` risk dimensions are excluded from the
  Red/Yellow/Green weighted average rather than folded into Yellow; if all 4
  come back Unknown, `overall` is `"Unrated"` instead of a fabricated
  Low/Medium/High.
- **Module 14 (Decision) — explicit thresholds, not a further Jev call.**
  By the time the decision is made, `business_quality`, `financial_quality`,
  and `valuation_verdict` are already fully-computed numbers — there's no
  genuine ambiguity left for Jev to resolve. The rule is: Reject if
  `business_quality < 6.5` or `financial_quality < 7.0`; Watchlist if both
  clear that bar but `valuation_verdict != "Attractive"`; Buy otherwise.

## Running it

Group each stock's inputs in their own folder under `Input\` — e.g.
`Input\Shilchar\Shilchar Tech.xlsx` and `Input\Shilchar\shilchar_brief.json`. The
report lands in the matching `Output\<Company>\` folder automatically (named
after whatever folder the Excel file lives in).

```bash
.venv\Scripts\python.exe stock_research_cookbook.py "Input\<Company>\<Company>.xlsx" "Input\<Company>\<company>_brief.json"
```

Results are cached to `stock_cache.json`, keyed by the exact content of the Excel
figures and brief text passed to each call — a different company or an edited brief
produces a fresh cache entry automatically; nothing needs to be cleared by hand.

### Companies without a screener.in export (e.g. non-Indian companies)

If `Input\<Company>\<Company>.xlsx` doesn't exist, the tool automatically fetches
financials from Yahoo Finance instead (`online_loader.py`, via the `yfinance`
package — `pip install yfinance`), using the `"ticker"` field in that company's
brief JSON (e.g. `"AAPL"`, `"RELIANCE.NS"`). Still pass the (non-existent) `.xlsx`
path on the command line as usual — it's only used to name the matching
`Output\<Company>\` folder:

```bash
.venv\Scripts\python.exe stock_research_cookbook.py "Input\AAPL\AAPL.xlsx" "Input\AAPL\aapl_brief.json"
```

Figures fetched this way are reported in the company's own currency and in
millions rather than screener.in's Rupee-Crore convention (`FinancialData.currency_symbol`
/ `unit_label` reflect this automatically in both the console and HTML output).

On Windows, run with `PYTHONUTF8=1` set (e.g. `PYTHONUTF8=1 .venv\Scripts\python.exe ...`
from Git Bash) — the brief text contains ₹ symbols, and Python's default file/console
encoding on Windows isn't UTF-8 unless this is set.

## Producing a brief JSON for a new stock

Run the prompt below in any capable chat LLM with the company's annual report,
investor presentation, or other filings attached or pasted in. Save its output
as `Input\<Company>\<company>_brief.json`, alongside that company's screener.in
Excel export.

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
  "ticker": "<exchange ticker symbol as recognized by Yahoo Finance, e.g. AAPL,
    RELIANCE.NS. Best-effort/optional -- include it when you can tell from the
    filings, but it is only actually required when no screener.in Excel export
    accompanies this brief (the tool then fetches financials online using it)>",
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
  "capital_return_evidence": {
    "current_shares_outstanding": "<latest diluted/outstanding share count with as-of date>",
    "shares_repurchased_last_3_fy": "<shares bought back each of the last 3 fiscal years>",
    "buyback_spend_last_3_fy": "<cash spent on buybacks each of the last 3 fiscal years>",
    "remaining_buyback_authorization": "<amount/shares still authorized, or 'None'>",
    "dividend_per_share_last_3_fy": "<dividend per share for each of the last 3 fiscal years>",
    "free_cash_flow_last_3_fy": "<free cash flow for each of the last 3 fiscal years>",
    "capital_return_policy": "<stated payout / buyback / dilution policy, incl. any share
      issuance or stock-based-comp dilution>"
  },
  "valuation_units": {
    "currency": "<ISO code of the price currency, e.g. INR, USD>",
    "unit": "<'crore' for a screener.in Excel (India) company, 'million' for a company
      fetched via the Yahoo Finance fallback>"
  },
  "valuation_scenarios": {
    "bear": {"scenario_weight": <0-1>, "assumption": "<what has to go wrong>",
      "fy_plus5_pat": <number, PAT 5 years out, in valuation_units.unit>,
      "exit_pe": <number>,
      "annual_share_count_change_pct": <number, e.g. -2.5 for net buybacks, +1 for dilution>,
      "annual_dividend_per_share": <number, average per-share dividend over the 5 years,
        in the price currency>},
    "base": {"scenario_weight": <0-1>, "assumption": "<the base case path>",
      "fy_plus5_pat": <number>, "exit_pe": <number>,
      "annual_share_count_change_pct": <number>, "annual_dividend_per_share": <number>},
    "bull": {"scenario_weight": <0-1>, "assumption": "<what has to go right>",
      "fy_plus5_pat": <number>, "exit_pe": <number>,
      "annual_share_count_change_pct": <number>, "annual_dividend_per_share": <number>}
  }
}

Important: `valuation_scenarios` is forward-looking analyst judgment, not something
extractable from historical filings — use your own reasoned 5-year assumptions per
scenario (grounded in the filings' disclosed growth plans, capacity expansions, margin
trends and capital-return record). Rules:

1. UNITS: never rely on the field name. `fy_plus5_pat` must be in the unit declared in
   `valuation_units` ("crore" for a screener.in/India company, "million" for a company
   fetched via the Yahoo Finance fallback -- see "Running it" above). The pipeline
   rejects a brief whose declared unit does not match the loaded financials.
2. WEIGHTS: `scenario_weight` values are analyst judgment, not statistical
   probabilities. They must sum to 1.0.
3. SHARE COUNT AND DIVIDENDS: the pipeline no longer holds shares flat. Set
   `annual_share_count_change_pct` from `capital_return_evidence` (net of buybacks
   and dilution) and `annual_dividend_per_share` from the dividend record. Use 0 only
   when the company genuinely neither buys back stock nor pays dividends. Do not
   assume buybacks the company's free cash flow cannot fund.
4. EXIT P/E: anchor to the company's own historical P/E range. A bull multiple above
   its historical high needs an explicit quality-of-business improvement (e.g. more
   recurring revenue, structurally higher margins) named in `assumption`; otherwise
   cap it at the historical high. Never combine optimistic earnings AND an
   above-history multiple without that justification.
5. ASSUMPTION TEXT: each `assumption` must state the implied 5-year PAT CAGR from the
   latest reported fiscal-year PAT. The bull case must list numeric hurdles (e.g.
   segment margin, FCF, mix targets) that have to be met. The bear case must cover
   volume-vs-price/mix erosion where relevant (e.g. price rises masking falling
   units).
6. SANITY CHECK: before finalizing, confirm that PAT / future shares x exit P/E gives a
   per-share price that is consistent with the story in `assumption`.
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
- Module 6's `"Unrated"` overall risk (all 4 dimensions came back `Unknown`) is scored
  as neutral in `_business_quality_score` (`risk_points = 2`, same as Medium), so a
  stock with too little risk evidence to rate isn't penalized or rewarded relative to
  a known-Medium-risk stock.
- The Yahoo Finance fallback (`online_loader.py`) typically only returns ~4 annual
  periods of financials vs. screener.in's up to 10 — 3-year CAGR/average figures sit
  right at the edge of what's available for a freshly-fetched company. It also relies
  on `yfinance`, an unofficial library that scrapes Yahoo Finance and can break when
  Yahoo changes its backend; a company with no populated statements raises a clear
  `ValueError` rather than silently producing an empty report. Dividend and bonus/
  split-issue data are thinner than screener.in's — dividends come from the cash-flow
  statement's aggregate payout rather than a per-share figure, and share counts are
  Yahoo's already split-adjusted series (unlike screener.in's as-filed figures), so
  no separate split/bonus correction is applied or needed.
