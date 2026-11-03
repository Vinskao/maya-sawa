# Test layout

Tests are grouped by feature: `market/` (including `macro/`, `reports/`, `portfolio/`, `watch/`), `research_pipeline/`, `blog/`, `social/`, `automation/`, `security/`, `integrations/`, `job_alerts/`, `api/`, and `infrastructure/`. Shared source fixtures remain in `fixtures/`.

Run the full suite with `poetry run python -m pytest`; run a domain with e.g. `poetry run python -m pytest tests/market/macro`. Some legacy infrastructure tests connect to the configured Redis or database and can write and delete fixed test keys; only run these against dedicated test services. Research pipeline PostgreSQL and real-model smoke tests require explicit environment configuration. No test has been disabled as part of this reorganization.
