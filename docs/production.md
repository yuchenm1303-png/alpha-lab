# Alpha Lab production deployment

The Vercel deployment is only a demo because its local filesystem is ephemeral. The production MVP should run on a persistent host with a mounted DuckDB volume.

## 1. Server environment

Create a server-side `.env` file next to `docker-compose.prod.yml`:

```env
HITHINK_API_KEY=replace_with_real_key
```

Do not commit this file.

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
- `real_sync_configured: true` when `HITHINK_API_KEY` is present
- `real_sync_enabled: true`

Then open `https://alpha.smirel.com` and use the web page's real-data sync card.

## 5. Important operational rule

Keep Uvicorn at one worker while DuckDB is the writable production store. The container command intentionally uses `--workers 1` to avoid multiple worker processes writing the same DuckDB file concurrently.

GitHub Actions also builds and publishes `ghcr.io/yuchenm1303-png/alpha-lab:latest` on pushes to `main`. If package visibility or registry authentication is inconvenient on the VPS, `docker compose ... up -d --build` remains the simplest fallback.
