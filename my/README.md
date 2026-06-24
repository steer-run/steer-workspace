# `my/` — your applications and dashboards

This is **your** space. Everything you (or your AI) author lives here, and **this is the folder your
Steer panel syncs**. A change under `my/` reaches your panel on the next sync (daily, or on demand);
changes anywhere else in the repo don't trigger anything.

| Path | What to put here |
|------|------------------|
| `templates/` | Your application templates — one `service.template` XML per app. |
| `dashboards/` | Your Grafana dashboards — one JSON per dashboard. |
| `logos/` | Logos referenced by your templates/dashboards. |
| `catalog_index.json` | Lightweight index of your apps (kept in sync by your tooling). |

## How to add an app

1. Copy the closest file from [`../examples/`](../examples/) into `templates/`.
2. Adapt it (see [`../AGENTS.md`](../AGENTS.md) for the rules: secrets, domains, backups, ports).
3. **Validate:** `python ../harness/validate.py templates/<your-app>.xml`
4. Commit & push. Your panel picks it up on the next sync.

> Keep `code` unique across your catalog. Everything in English.
