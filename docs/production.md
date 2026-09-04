# Alpha Lab production deployment

The Vercel deployment is only a demo because its local filesystem is ephemeral. The production MVP should run on a persistent host with a mounted DuckDB volume.

## 1. Server environment

Copy `.env.example` to a server-side `.env` file next to `docker-compose.prod.yml` and replace both secrets:

```env
ALPHALAB_ADMIN_TOKEN=generate_a_long_random_value
HITHINK_API_KEY=replace_with_real_key
```

Do not commit `.env` or either secret. `ALPHALAB_ADMIN_TOKEN` protects every endpoint that mutates the database or consumes upstream sync quota. The browser sends it only as `X-Admin-Token` for the current write request; the UI does not persist it to localStorage/sessionStorage.

## 2. Start the service

You can build directly from the repository:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The app is bound only to the host loopback interface:

```text
127.0.0.1:8091 -> container:8000
```

The named volume `alpha-lab-data` stores `/data/alpha_lab.duckdb`, so restarts and container upgrades do not delete historical data.

## 3. Caddy

Add a separate site block to the existing Caddy configuration. Do not change the existing TermRelay routes:

```caddy
alpha.smirel.com {
    reverse_proxy 127.0.0.1:8091
}
```

Then validate and reload Caddy using the same deployment procedure already used on the server.

## 4. Verify

```bash
curl http://127.0.0.1:8091/api/health
```

Expected production characteristics:

- `persistent_storage: true`
- `write_auth_configured: true`
- `real_sync_configured: true` when `HITHINK_API_KEY` is present
- `real_sync_enabled: true` only when persistence, write auth, and HiThink are all ready

Then open `https://alpha.smirel.com`, enter the admin token when you need a write operation, and use the real-data sync card.

## 5. Write API security

These endpoints require the `X-Admin-Token` header:

- `POST /api/sync/historical`
- `POST /api/import/bars`
- `POST /api/import/popularity`

Read-only health/stats and historical analysis remain usable without the admin token.

If `ALPHALAB_ADMIN_TOKEN` is missing on the server, all write endpoints fail closed with HTTP 503. An incorrect/missing request token returns HTTP 401.

## 6. Important operational rule

Keep Uvicorn at one worker while DuckDB is the writable production store. The container command intentionally uses `--workers 1` to avoid multiple worker processes writing the same DuckDB file concurrently.

GitHub Actions also builds and publishes `ghcr.io/yuchenm1303-png/alpha-lab:latest` on pushes to `main`. If package visibility or registry authentication is inconvenient on the VPS, `docker compose ... up -d --build` remains the simplest fallback.
