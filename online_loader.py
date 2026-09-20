"""Fallback loader that fetches financials from Yahoo Finance via `yfinance`, for
companies that don't have a screener.in Excel export (e.g. non-Indian listings).

Returns the same `FinancialData` shape that `excel_loader.load_financials` builds,
so every one of the 14 framework modules and `html_report.py` works unmodified.
The only structural difference: monetary series here are stored in millions
(`unit_divisor=1e6`) rather than screener.in's Rupee-Crore convention
(`unit_divisor=1e7`) -- see `FinancialData.unit_divisor`/`unit_label`.
"""

from __future__ import annotations

import yfinance as yf

from excel_loader import FinancialData

_UNIT_DIVISOR = 1e6
_UNIT_LABEL = "M"

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}


def _common_periods(*dfs) -> list:
    """Column (period-end) timestamps present in every statement, oldest -> newest.

    The three statements aren't guaranteed to share identical columns, so rows are
    looked up by matching period rather than by position.
    """
    common = set(dfs[0].columns)
    for df in dfs[1:]:
        common &= set(df.columns)
    return sorted(common)


def _row(df, periods: list, *names: str, scale: bool = True) -> list[float]:
    """First matching row (label spelling varies by yfinance version/ticker), as a
    list aligned to `periods` (oldest -> newest), scaled to _UNIT_DIVISOR unless
    scale=False (used for share counts, which aren't a monetary amount)."""
    divisor = _UNIT_DIVISOR if scale else 1.0
    for name in names:
        if name in df.index:
            row = df.loc[name]
            return [
                (v / divisor) if (p in row.index and row[p] == row[p]) else 0.0
                for p, v in ((p, row.get(p)) for p in periods)
            ]
    return [0.0] * len(periods)


def load_financials_online(ticker: str) -> FinancialData:
    t = yf.Ticker(ticker)
    income = t.income_stmt
    balance = t.balance_sheet
    cash = t.cashflow
    info = t.info

    if income is None or income.empty or balance is None or balance.empty or cash is None or cash.empty:
        raise ValueError(f"yfinance returned no financial statements for ticker {ticker!r}")

    periods = _common_periods(income, balance, cash)
    if "Total Revenue" in income.index:
        # yfinance's oldest annual column is frequently a stub with no populated
        # rows at all (a known quirk, not missing data specific to this ticker) --
        # drop any period revenue itself is NaN for rather than let it flow through
        # downstream as a fake zero-value year.
        revenue_row = income.loc["Total Revenue"]
        periods = [p for p in periods if p in revenue_row.index and revenue_row[p] == revenue_row[p]]
    if not periods:
        raise ValueError(f"yfinance's income/balance/cash-flow statements for {ticker!r} share no common period")
    fiscal_year_ends = [p.to_pydatetime().replace(tzinfo=None) for p in periods]

    pbt = _row(income, periods, "Pretax Income")
    interest = _row(income, periods, "Interest Expense")
    depreciation = _row(income, periods, "Reconciled Depreciation")
    if not any(depreciation):
        depreciation = _row(cash, periods, "Depreciation And Amortization")
    ebit = _row(income, periods, "EBIT")
    if not any(ebit):
        ebit = [p_ + i for p_, i in zip(pbt, interest)]

    net_block = _row(balance, periods, "Net PPE")

    # Unlike screener.in's as-filed share counts (which need face_value_history to
    # net out splits/bonus issues in unexplained_share_increase_pct), yfinance's
    # "Ordinary Shares Number" series is already retroactively split-adjusted --
    # applying a split correction on top of that double-counts it. A flat history
    # (no correction) is therefore the right choice here, not an oversight.
    face_value_history = [1.0] * len(periods)

    currency = (info.get("currency") or "USD").upper()
    currency_symbol = _CURRENCY_SYMBOLS.get(currency, currency + " ")

    company_name = info.get("longName") or info.get("shortName") or ticker

    return FinancialData(
        company_name=company_name,
        fiscal_year_ends=fiscal_year_ends,
        sales=_row(income, periods, "Total Revenue"),
        net_profit=_row(income, periods, "Net Income", "Net Income Common Stockholders"),
        dividend=[abs(v) for v in _row(cash, periods, "Cash Dividends Paid")],
        pbt=pbt,
        tax=_row(income, periods, "Tax Provision"),
        interest=interest,
        depreciation=depreciation,
        other_income=_row(income, periods, "Other Income Expense", "Other Non Operating Income Expenses"),
        operating_profit=_row(income, periods, "Operating Income"),
        ebit=ebit,
        cfo=_row(cash, periods, "Operating Cash Flow"),
        capex_approx=[abs(v) for v in _row(cash, periods, "Capital Expenditure")],
        equity=_row(balance, periods, "Common Stock Equity", "Stockholders Equity"),
        debt=_row(balance, periods, "Total Debt"),
        receivables=_row(balance, periods, "Receivables", "Accounts Receivable"),
        inventory=_row(balance, periods, "Inventory"),
        cash_and_bank=_row(balance, periods, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
        # "Investments And Advances" is non-current marketable securities only --
        # yfinance reports current marketable securities as a separate row
        # ("Other Short Term Investments"), which excel_loader's ROIC/net-cash math
        # (which treats "investments" as all surplus marketable securities) needs
        # added back in, or it understates net cash by the current-securities amount.
        investments=[
            a + b for a, b in zip(
                _row(balance, periods, "Investments And Advances", "Available For Sale Securities"),
                _row(balance, periods, "Other Short Term Investments"),
            )
        ],
        net_block=net_block,
        cwip=[0.0] * len(periods),
        num_shares=_row(balance, periods, "Ordinary Shares Number", "Share Issued", scale=False),
        new_bonus_shares=[0.0] * len(periods),
        face_value_history=face_value_history,
        current_price=info.get("currentPrice") or info.get("regularMarketPrice") or 0.0,
        market_cap=(info.get("marketCap") or 0.0) / _UNIT_DIVISOR,
        face_value=1.0,
        currency_symbol=currency_symbol,
        unit_label=_UNIT_LABEL,
        unit_divisor=_UNIT_DIVISOR,
    )
