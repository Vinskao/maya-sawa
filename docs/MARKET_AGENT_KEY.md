# Scheduled analysis routine write key

The scheduled Claude Code routine refreshes the market AI analyses twice a day. It has no Keycloak login, so it
writes with a dedicated key sent as the `X-Market-Agent-Key` header.

- **Server side:** `MARKET_AGENT_KEY_SHA256` in `k8s/deployment.yaml` holds only the key's SHA-256. The repository
  and the deployment config never contain a usable secret.
- **Scope:** the key can call `PUT /market/dashboard/analysis/{code}` for `productType` stock, futures, macro or
  macro-node (one analysis per macro logic-chain node, code = the node id upper-cased; all of them are read with
  `GET /market/dashboard/macro/nodes`, see the frontend `docs/MACRO_LOGIC_CHAINS.md`), and the
  report-library routine endpoints `GET /market/reports/pending`, `PUT /market/reports/{id}/claims`, and
  `GET /market/reports/search` (public reports by default; private reports only with `include_private=true`). The
  semantic search endpoint requires this key for `include_private=true`. Published analyses must use public reports only.
  Since 2026-10-26 it can also call `PUT /market/dashboard/targets/{code}?market=TW|JP|US|KR|HK` to add broker target
  prices found in news (`actions[]` of firm, date, target, rating?, previousTarget?, thesis? (the broker's reasoning,
  at most 300 characters, since 2026-10-27), reportId? (a library report it came from), sourceUrl; every row needs the
  article URL, a past date and a positive target; same firm and date replaces). Yahoo Finance fills US per-broker
  targets and every market's consensus automatically each day at 08:30 Taipei, so the routine only adds Taiwan/Japan
  brokers. Code: `services/market_price_targets.py`. Since 2026-10-26 the Taiwan routine's prompt has a section 7 for
  this: read the stored targets, search the last 30 days of news (TW, JP, KR), write only targets an article states
  with the broker, number and date, use one fixed name per broker so the chart joins a broker's targets, and list what
  was added in the final report. Codes are bare (`6857` with `market=JP`, not `6857-JP`).
  It cannot upload, download, list, or delete reports, change
  visibility, or edit research maps. Every other endpoint still requires a login.
- **Edit history:** saves are recorded with editor `agent:scheduled-analysis` and keep the normal revision history.
- **Routine side:** the key is a **network secret** on the routine's claude.ai cloud environment (header
  `X-Market-Agent-Key`, no prefix, host `peoplesystem.tatdvsonorth.com`). The agent proxy adds it outside the session VM,
  so the routine never sees it. The key must never appear in a prompt, the repository or a log.

## Rotate or revoke

1. Generate a new random key, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Put `sha256(key)` in `MARKET_AGENT_KEY_SHA256` and deploy maya-sawa.
3. In the cloud environment, delete the network secret and add it again with the new value.

To revoke without a new key, set `MARKET_AGENT_KEY_SHA256` to an empty string and deploy.

## Routines (claude.ai/code/routines, environment "Default")

| Routine | When (Taipei) | Cron (UTC) | Scope |
|---|---|---|---|
| Market report claim extraction `trig_018MeBwwU74WvydGHRaRt6Wd` | Daily 20:30 | `30 12 * * *` | Extract report claims without OpenAI; subscription Claude Code routine |
| 市場 AI 分析｜台股收盤後 `trig_01ECP68tWfgM749sJa3gBiN9` | Mon–Fri 21:15 | `15 13 * * 1-5` | Taiwan holdings, TXF, JP/KR holdings |
| 市場 AI 分析｜美股與總經 `trig_01NETQT5DCSHj4TKwv45nbJR` | Tue–Sat 07:30 | `30 23 * * 1-5` | macro commentary first, then US holdings |
| 每週維護｜ty-multiverse-backend `trig_01JEDibagHGmSFZ7D7nTLhLz` | Wed 01:00 | `0 17 * * 2` | Dependency/framework updates, small refactors; opens a PR to `main` |
| 每週維護｜ty-multiverse-consumer `trig_01CsCHXk4X7zPkjb1EPf4xBL` | Thu 01:00 | `0 17 * * 3` | Same, PR to `main` |
| 每週維護｜ty-multiverse-gateway `trig_018TNJoPunQ8N7PcgdbtCEqE` | Fri 01:00 | `0 17 * * 4` | Same, PR to `main` |
| 每週維護｜maya-sawa `trig_01LRDWjEdkEH5PKjSpfW8YfN` | Sat 01:00 | `0 17 * * 5` | Same, PR to `main` (the one exception to "main only, no branches") |
| 每週維護｜ty-multiverse-frontend `trig_01RbWXpne4jvHA1B737V6PSw` | Sun 01:00 | `0 17 * * 6` | Same plus small UI fixes, PR to `dev` |

- **Weekly maintenance (added 2026-10-28):** each run only opens a PR (never merges or pushes the base branch, which would deploy through Jenkins), then sends one Telegram note with the PR link via `/market/notify` and reports token usage. The Java runs also clone `ty-multiverse-common` and `mvn install` it locally, because the cloud has no GitHub Packages token. Connectors (Gmail, Drive, etc.) are removed from these routines on purpose: they read external changelogs and need no account access.

- **Taiwan run timing (changed 2026-10-19):** margin balances and securities lending (TWSE MI_MARGN/TWT93U and the TPEx
  equivalents) were first seen at 20:51 on 2026-10-19 by a 10-minute poll, so they publish around 20:45. Prices are out by
  about 15:00 and institutional flows by 16:30. The second history pass now runs at 21:00 (was 22:00) and the Taiwan
  run at 21:15 (was 18:40), so each analysis includes the day's margin data.
- **Model:** both run Claude Sonnet 5.5 on the subscription.
- **Environment setup:** the cloud environment needs only the network secret. Its host is reachable even at the
  default **Trusted** network level.

## Catch-up runs after the IB login (`services/market_automation.py`)

IBKR needs a manual login about once a day, so Japan, Korea and US bars only arrive while the session is alive.
The routines run on their own cron (Taiwan 21:15 Mon–Fri, US 07:30 Tue–Sat, Taipei). Since 2026-10-23 maya-sawa
only re-runs a routine whose scheduled run missed the IB data; a day with IB up fires nothing extra.

Flow (asynchronous, human in the loop):
1. The scheduled run finds stale overseas bars, updates what it can and pushes a login reminder to the owner's phone.
2. maya-sawa marks that session missed (`<run>:missed` in `maya_sawa_market_routine_fire`) once the scheduled time
   has passed and the bars are still older than the close.
3. The owner runs `ibkr-gateway\login.ps1`. maya-sawa opens the market-data session and collects the bars within
   about 4 minutes.
4. maya-sawa fires the routine again with a catch-up note (at most once per session, not before 15 minutes after
   the scheduled time so the two runs do not overlap). Holdings already updated today are skipped as having no new
   data.

- **When a catch-up fires:** a session marked missed, not yet caught up, and every holding in the run's markets has
  bars collected after the close (Taiwan, JP and KR close at 14:30 Taipei; US at 05:30). Logins after midnight
  leave that day to the next scheduled run.
- **When it is checked:**
  - after every IBKR collection pass;
  - when the owner opens the site (`POST /market/automation/check`).

  The site then shows an IB login reminder and each run's state.
- **What "logged in" means:** the portfolio reads *and* the gateway's market-data session (`POST /iserver/auth/status`,
  `authenticated` and `connected`) were both seen within 15 minutes. The two lapse separately: on 2026-10-19/20 the
  portfolio kept answering while `/iserver` returned `400 no bridge`, so no bars came in for a day and, because only the
  portfolio was checked, no login reminder appeared. Each 4-minute pass now records the session as
  `ACCOUNT/PRIVATE/iserver_session`.
- **While logged out:** `/iserver` collection is skipped instead of failing every few minutes. On the first pass after a
  login, failed fetches are retried at once instead of waiting out the one-hour error backoff, so the bars arrive
  within about 4 minutes and the due routines can fire.
- **Fire tokens:** routine API trigger tokens, held in the optional Jenkins credentials `MARKET_ROUTINE_TAIWAN_TOKEN` and
  `MARKET_ROUTINE_US_TOKEN`. Jenkins puts them in the k8s Secret `market-routine-fire`. Without them, nothing is fired
  and runs report `not-configured`. As of 2026-10-23 neither is set in production.
- **New custom picks (since 2026-10-25):** saving the custom list (`PUT /market/dashboard/custom`) finds the picks that
  were not saved before. It backfills their history and futures bars, queues their FinMind statements first, and then
  fires the Taiwan routine for just those codes, so the first analysis doesn't wait for 21:15. Each code fires at most
  once per Taipei day (`AutomationFire.run` = `added:<productType>:<code>`); a failed fire is released and the next save
  retries. Without `MARKET_ROUTINE_TAIWAN_TOKEN` the data is still filled and only the analysis waits for the schedule.
  Code: `market_automation.analyze_added`; tests: `tests/test_market_custom_added.py`.
- **States reported:** `no-session`, `scheduled` (the cron run covers it), `waiting-ib` (missed, waiting for the
  login and bars), `fired`, `done`, `not-configured`, `error` (released and retried on the next check).
