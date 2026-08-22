# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A single-file Python script (`stockSender.py`) that fetches stock/news data and emails an HTML market dashboard daily. No framework, no tests, no build step.

## Running

```bash
# Requires three environment variables
export EMAIL_ADDRESS="your@gmail.com"
export EMAIL_PASSWORD="your_app_password"
export TO_EMAIL="recipient@gmail.com"

python stockSender.py
```

Gmail requires an App Password (not the account password) when 2FA is enabled.

## External APIs

- **Finnhub** (`API_KEY`): stock quotes, company profiles, company news — hardcoded key at top of file
- **NewsAPI** (`NEWS_API_KEY`): general news for focus companies — hardcoded key at top of file

Both keys are hardcoded in the script. If they stop working, they need to be rotated.

## Architecture

Everything lives in `stockSender.py`. The flow is linear:

1. **Data fetch** — `get_stock_data()` (portfolio + watchlist), `get_stock_news()` (Finnhub news per ticker), `get_focus_news()` (NewsAPI for Accenture/Mondelez/SAP), `get_market_top_movers()` (parallel fetch of `TOP_TICKERS` via `ThreadPoolExecutor`)
2. **HTML generation** — `create_summary_section()`, `create_stock_table()`, `create_collapsible_news_section()`, assembled in `create_email_content()`
3. **Send** — `send_email()` via `smtplib` over SSL to `smtp.gmail.com:465`

## Key Data Structures

- `tickers` — portfolio companies → ticker symbols
- `buy_prices` — purchase price per company (used to compute gain/loss %)
- `dividend_yields` — static, manually maintained
- `watchlist` — potential buys (no buy price tracking)
- `focus_companies` + `focus_keywords` — companies covered by the "Company Digest" section via NewsAPI
- `TOP_TICKERS` — broad market list scanned for top movers

The "Status vs Buy" column color uses `get_gradient_color()` — opacity scales with distance from buy price (capped at ±30%).
