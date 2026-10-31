# Overseas data collection (2026-10-16)

## Implemented

- IBKR CPAPI: contract profile; daily OHLCV (one-year initial backfill, weekly incremental window every six hours); market snapshots with change, day range, volume, bid/ask, historical volatility and live/delayed/frozen entitlement status.
- PostgreSQL `maya_sawa_ibkr_datasets` is the durable source. Per-market code identity and broker conid are retained. `latest` retains last success; `attempt` records failures. Daily observations, raw history responses, quote snapshots and private portfolio snapshots are stored. Private snapshots have no public route.
- Portfolio refresh writes PostgreSQL before Redis; Redis loss falls back to PostgreSQL. Public research GET uses DB plus 60-second local cache; never calls a broker/provider per request.
- SEC EDGAR companyfacts supplements US holdings META and LITE without a key. Original XBRL and normalized financials are persisted. Daily polling uses content-addressed archives: identical filings do not create new daily copies. Changed values/revisions preserve a new source version.
- Financials preserve exact start/end, fiscal year/quarter, currency/unit, filing date, form and accession. Single-quarter, annual, cumulative YTD and instant balance-sheet data remain separate. EPS is USD/share; other monetary amounts are USD. Missing fourth-quarter XBRL facts are not fabricated. Current/noncurrent debt remain distinct. Cost/revenue-derived gross profit is explicitly marked.

Public route: `GET /market/dashboard/overseas/{code}?market=US|JP|KR|HK`; frontend proxy: `/api/market/dashboard/overseas/{code}?market=...`. `datasets.financials` and each dataset's `fetchedAt`, `coverage`, `technical.asOf`, latest daily date and `gaps` are available to AI agents. Do not treat fetchedAt as a publication date or broker snapshot update time as guaranteed exchange trade time. Read source availability; do not call frozen/delayed prices real time.

## Verified production initial backfill

| Code | Market | Valid daily bars | Last date | Quote availability |
| --- | --- | ---: | --- | --- |
| META | US | 250 | 2026-10-15 | DPB (delayed) |
| LITE | US | 250 | 2026-10-15 | DPB (delayed) |
| 6857 | JP | 242 | 2026-10-16 | DB (delayed) |
| 6524 | JP | 241 | 2026-10-15 | DB (delayed) |
| 000660 | KR | 235 | 2026-10-16 | ZB (frozen) |

Invalid zero-price bars stay in raw responses, but are excluded from normalized series. IB OHLC values are already price-scaled. Normalized volume = raw v × volumeFactor; both raw v and factor remain available.

## Remaining gaps

IB deprecated EPS/PE/market-cap/dividend/beta snapshot tags on 2026-01-06. Complete Japanese and Korean financials require another source: EDINET v2 and OpenDART require separately registered API keys. These keys have not been configured in this implementation. Analyst consensus, ownership/institutional flows and short interest are not supplied by the implemented endpoints. Do not use a same-number Taiwan ticker as a fallback. Do not enable paid regulatory snapshots, paid subscriptions or paid vendors automatically.

SEC CIK mappings currently cover META and LITE; additional US holdings require a verified CIK mapping in `overseas_financials.py`. New IB holdings with conid are collected automatically for supported markets. Agent research must rediscover holdings and read current source coverage each run; do not assume the five initial tickers remain the universe.

## Tests and sources

Tests: `poetry run python -m pytest tests/test_overseas_financials.py tests/test_ibkr_research.py tests/test_market_dashboard.py tests/test_market_brief.py -q`.

Tests cover real trimmed source samples, units/timezones, source identity, missing values, invalid bars, Redis-loss replay, failure preservation, source TTL, public-field allowlisting, source timestamps, financial fiscal periods/YTD separation, restatements, Lumentum's including-tax revenue tag and content-addressed archive identity. Unit-test HTTP responses are mocked.

- https://www.interactivebrokers.com/docs/web-api/changelog
- https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data
- https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/market-data-fields
- https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0090.html
- https://opendart.fss.or.kr/intro/main.do
