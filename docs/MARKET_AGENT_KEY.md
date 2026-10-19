# Scheduled analysis routine write key

The scheduled Claude Code routine refreshes the market AI analyses twice a day. It has no Keycloak login, so it
writes with a dedicated key sent as the `X-Market-Agent-Key` header.

- **Server side:** `MARKET_AGENT_KEY_SHA256` in `k8s/deployment.yaml` holds only the key's SHA-256. The repository
  and the deployment config never contain a usable secret.
- **Scope:** the key can only call `PUT /market/dashboard/analysis/{code}` for `productType` stock, futures or macro.
  - Research maps return 403.
  - Every other endpoint still requires a login.
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
| 市場 AI 分析｜台股收盤後 `trig_01ECP68tWfgM749sJa3gBiN9` | Mon–Fri 21:15 | `15 13 * * 1-5` | Taiwan holdings, TXF, JP/KR holdings |
| 市場 AI 分析｜美股與總經 `trig_01NETQT5DCSHj4TKwv45nbJR` | Tue–Sat 07:30 | `30 23 * * 1-5` | macro commentary first, then US holdings |

- **Taiwan run timing (changed 2026-10-19):** margin balances and securities lending (TWSE MI_MARGN/TWT93U and the TPEx
  equivalents) were first seen at 20:51 on 2026-10-19 by a 10-minute poll, so they publish around 20:45. Prices are out by
  about 15:00 and institutional flows by 16:30. The second history pass now runs at 21:00 (was 22:00) and the Taiwan
  run at 21:15 (was 18:40), so each analysis includes the day's margin data.
- **Model:** both run Claude Sonnet 5.5 on the subscription.
- **Environment setup:** the cloud environment needs only the network secret. Its host is reachable even at the
  default **Trusted** network level.

## Automatic runs after the IB login (`services/market_automation.py`)

IBKR needs a manual login about once a day, so Japan, Korea and US bars only arrive while the session is alive.

- **When a run fires:** at most once per session, as soon as both of these hold:
  - its markets have closed and the day's data is in: Taiwan, JP and KR close at 14:30 Taipei Mon–Fri but the run waits
    until 21:10 for margin data (`fire_after`); US at 05:30 Taipei Tue–Sat;
  - every holding in those markets has bars collected after the close.
- **When it is checked:**
  - after every IBKR collection pass;
  - when the owner opens the site (`POST /market/automation/check`).

  The site then shows an IB login reminder and each run's state.
- **Fire tokens:** routine API trigger tokens, held in the optional Jenkins credentials `MARKET_ROUTINE_TAIWAN_TOKEN` and
  `MARKET_ROUTINE_US_TOKEN`. Jenkins puts them in the k8s Secret `market-routine-fire`. Without them, nothing is fired
  and runs report `not-configured`.
- **Fixed schedules:** still run as a fallback.
