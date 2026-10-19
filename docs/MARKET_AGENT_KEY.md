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
| 市場 AI 分析｜台股收盤後 `trig_01ECP68tWfgM749sJa3gBiN9` | Mon–Fri 18:40 | `40 10 * * 1-5` | Taiwan holdings, TXF, JP/KR holdings |
| 市場 AI 分析｜美股與總經 `trig_01NETQT5DCSHj4TKwv45nbJR` | Tue–Sat 07:30 | `30 23 * * 1-5` | macro commentary first, then US holdings |

- **Taiwan run timing:** the 18:40 run follows the 18:20 history pass. Margin and borrowed-share data that publish later
  are picked up by the 22:00 pass and land in the next run.
- **Model:** both run Claude Sonnet 5.5 on the subscription.
- **Environment setup:** the cloud environment needs only the network secret. Its host is reachable even at the
  default **Trusted** network level.
