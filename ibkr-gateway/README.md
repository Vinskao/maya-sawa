# IBKR Client Portal Gateway (OKE)

Runs IBKR's Client Portal Gateway (CPAPI v1) in-cluster so `maya-sawa` can read
the account balance. The gateway proxies to `api.ibkr.com` and holds the
authenticated session **in memory** — it is established by a human browser login
and is **not** persisted across pod restarts.

## What this deploys
- `Deployment/ibkr-gw` (1 replica, `Recreate`) on port 5000 (self-signed TLS).
- `Service/ibkr-gw` (ClusterIP) — internal only, no Ingress.
- `maya-sawa` reads it via `IBKR_GATEWAY_URL=https://ibkr-gw:5000` (verify=False).

`root/conf.yaml` allows the pod CIDR (`10.*`) so maya-sawa and the port-forward
localhost can reach it; without that the gateway returns 403.

## Build & deploy
This lives **inside the maya-sawa repo** (`maya-sawa/ibkr-gateway/`) and shares
maya-sawa's Jenkins pipeline — the `Build & Push IBKR Gateway` stage builds this
dir's image (`papakao/ibkr-gateway:latest`, build context `ibkr-gateway/`) and the
Deploy stage applies `ibkr-gateway/k8s/deployment.yaml`. So a normal maya-sawa
build rebuilds and redeploys the gateway too (and brings up maya-sawa with
`IBKR_ENABLED=true`). The maya-sawa `.dockerignore` excludes `ibkr-gateway/` so the
12MB vendored runtime doesn't bloat the maya-sawa image context.

Manual fallback (run from the `maya-sawa/` repo root):

```bash
docker build -t papakao/ibkr-gateway:latest ibkr-gateway
docker push papakao/ibkr-gateway:latest
kubectl apply -f ibkr-gateway/k8s/deployment.yaml
kubectl rollout restart deployment/ibkr-gw -n default
```

## Authenticating the gateway (required after every restart / ~daily)
IBKR has **no headless login** for retail accounts. Each time the session lapses
(hard expiry ~24h, or a pod restart), a human must log in through a browser:

```bash
# 1. Forward the in-cluster gateway to your machine
kubectl port-forward deployment/ibkr-gw 5000:5000 -n default

# 2. Open it, bypass the self-signed cert warning (type: thisisunsafe),
#    log in with IBKR username/password + 2FA, wait for "Client login succeeds"
open https://localhost:5000

# 3. Confirm the session is live
curl -sk https://localhost:5000/v1/api/portfolio/accounts
```

Within ~4 min maya-sawa's background refresh writes the IBKR snapshot to Redis
and the Account Portfolio card picks it up. The same refresh (every 240s) keeps
the session alive between the ~daily manual logins.

## Operational notes
- If the card shows no IBKR data, check: gateway pod running, session still
  authenticated (`portfolio/accounts` returns JSON not a login redirect), and
  `kubectl logs deployment/maya-sawa` isn't logging "Skipping IBKR merge".
- A pod restart (node drain, redeploy) drops the session — re-run the login.
- Consider alerting when `/v1/api/tickle` stops returning `authenticated:true`.
