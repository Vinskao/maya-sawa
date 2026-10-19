# Scheduled analysis routine write key

The scheduled Claude Code routine refreshes the market AI analyses twice a day. It has no Keycloak login, so it
writes with a dedicated key sent as the `X-Market-Agent-Key` header.

- **Server side:** `MARKET_AGENT_KEY_SHA256` in `k8s/deployment.yaml` holds only the key's SHA-256. The repository
  and the deployment config never contain a usable secret.
- **Scope:** the key can only call `PUT /market/dashboard/analysis/{code}` for `productType` stock, futures or macro.
  - Research maps return 403.
  - Every other endpoint still requires a login.
- **Edit history:** saves are recorded with editor `agent:scheduled-analysis` and keep the normal revision history.
- **Routine side:** the key is stored as the `MARKET_AGENT_KEY` environment variable of the routine's claude.ai cloud
  environment. It must never appear in a prompt, the repository or a log.

## Rotate or revoke

1. Generate a new random key, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Put `sha256(key)` in `MARKET_AGENT_KEY_SHA256` and deploy maya-sawa.
3. Replace `MARKET_AGENT_KEY` in the cloud environment settings.

To revoke without a new key, set `MARKET_AGENT_KEY_SHA256` to an empty string and deploy.
