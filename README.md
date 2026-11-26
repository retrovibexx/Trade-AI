# Trade AI

A starter web app for multi-market charts and candle-close alerts.

## Included
- Mobile candlestick chart with zoom/pan and timeframe selector.
- UT Bot-style ATR trailing stop (Key Value 1, ATR 10, Heikin Ashi off).
- Independent technical confirmation: EMA 20 direction plus RSI 14 regime. This is a rule-based filter, **not a trained AI/ML model**.
- Server-side scanner, SQLite signal de-duplication, PWA manifest, service worker and Web Push endpoint.

## Data and trading limitations
The adapter uses Yahoo Finance via yfinance. It is not a guaranteed real-time feed; futures, forex and intraday coverage can be delayed, limited or unavailable. The 4-hour timeframe is aggregated from hourly candles. Validate timestamps and feed quality before relying on alerts. TradingView data subscriptions do not automatically license data for this app.

Signals are evaluated on completed candles only. The scanner polls at the configured interval, so notification delivery is not instantaneous at the exact candle close. No broker order execution is included. This is an alerting/analysis starter, not financial advice.

## Deploy on Render
1. Sign in to Render and choose New → Blueprint.
2. Connect GitHub repository retrovibexx/Trade-AI and select main.
3. Review and deploy. The blueprint uses a paid Starter web service because a sleeping free service is unsuitable for an always-running scanner.
4. Set VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, and VAPID_CLAIMS_EMAIL in the service environment. Use valid Web Push VAPID credentials and keep the private key secret. Without these keys, the app loads but push notifications will not send.
5. Check /api/health for ok: true.

For persistence, attach a Render persistent disk at /var/data and set DATABASE_PATH=/var/data/trade_ai.db. Without this, SQLite data may be lost on redeploy/restart. Do not run multiple scanner instances against the same SQLite database.

## Configure markets
Set SCAN_SYMBOLS to comma-separated Yahoo Finance symbols, e.g. SPY,QQQ,YM=F,ES=F,GC=F,EURUSD=X. Set SCAN_INTERVALS to values such as 15m,1h,4h,1d. Yahoo Finance interval and retention limits apply. SCAN_SECONDS controls polling frequency (minimum 30 seconds).

## iPhone notifications
1. Deploy over HTTPS.
2. Open the deployed URL in Safari.
3. Use Share → Add to Home Screen.
4. Launch Trade AI from the Home Screen.
5. Tap Enable notifications and allow permission.

Push requires valid VAPID keys and a persistent backend. iOS/browser support and notification settings can vary by device and OS version.

## Local run
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

Open http://127.0.0.1:8000.
