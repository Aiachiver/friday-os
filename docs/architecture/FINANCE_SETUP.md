# Financial intelligence (Phase 4)

No API key required — market data, news, and technical analysis all run
through `yfinance` (free, no signup). Just start asking:

- *"What's Apple trading at?"* → `get_stock_price`
- *"Analyze Tesla for me"* / *"What's the RSI on Reliance?"* → `analyze_stock`
- *"Show me a chart of Bitcoin"* → `get_price_chart` (saved to
  `data/user_files/charts/`, path spoken back to you)
- *"What's the news sentiment on Infosys?"* → `get_news_sentiment`
- *"I bought 10 shares of AAPL at $145"* → `add_portfolio_holding`
- *"How's my portfolio doing?"* → `get_portfolio_summary` (live P/L)
- *"Alert me when Bitcoin goes above $70,000"* → `set_price_alert`

## Ticker conventions

| Asset | Format | Example |
|---|---|---|
| US stocks | Plain ticker | `AAPL`, `TSLA` |
| Indian stocks (NSE) | `.NS` suffix | `RELIANCE.NS`, `TCS.NS` |
| Indian stocks (BSE) | `.BO` suffix | `INFY.BO` |
| Crypto | `-USD` suffix | `BTC-USD`, `ETH-USD` |
| Forex | `=X` suffix | `EURUSD=X`, `USDINR=X` |
| Commodities | Futures code | `GC=F` (gold), `SI=F` (silver) |

FRIDAY's system prompt already knows these conventions, so you can just
say "Reliance" or "Bitcoin" in conversation and it will map that to the
right ticker most of the time — if it gets it wrong, just tell it the
exact symbol.

## Price alerts run in the background

A scheduled job checks all active alerts every 60 seconds (configurable
via `config/settings.yaml` → `finance.alert_check_interval_seconds`) —
you don't need FRIDAY listening or the dashboard open for an alert to
fire; as long as the app is running, it'll speak a notification the
moment a target price is crossed.

## Safety framing (by design, not just prompting)

Every technical analysis result carries an explicit disclaimer field
baked into the data itself (`app/finance/analysis.py`), and the system
prompt separately instructs the AI never to phrase indicators as
guaranteed predictions or tell you to buy/sell. This is intentionally
redundant — the disclaimer survives even if a smaller/local model
doesn't follow the system prompt's finance framing perfectly.

FRIDAY's financial analysis is informational only, not financial advice.
