# RepoScout SaaS API contract

The plugin is source-independent from the RepoScout SaaS repository. It connects
to the production API at `https://reposcout-api.nouran-darwish-ai.dev`.

## Endpoints

### Validate an API key

`GET /api/v1/reposcout/validate-key`

The plugin sends `X-API-Key` when a key is configured. The compatible response
contains `allowed`, `tier`, `calls_today` and `daily_limit`.

### Record usage

`POST /api/v1/reposcout/usage`

The request can include `tool_name`, `query`, `results_count` and `chosen_repo`.
A valid request returns HTTP `201`.

## Compatibility policy

- Plugin major version `N` targets backend major version `N`.
- The backend may add optional response fields without a plugin major release.
- Removing or renaming fields requires coordinated major releases.
- Local development can set `REPOSCOUT_BACKEND_URL=http://localhost:8000`.

Server-side contract tests live in `Nouran99/RepoScout`; client behavior and
outage-policy tests live in this repository.
