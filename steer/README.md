# `steer/` — Steer's official catalog (read-only)

This folder mirrors **Steer's official catalog**: the curated templates and dashboards that ship with
the platform. It is here as **reference and few-shot material** for you and your AI.

**Do not edit anything under `steer/`.** Your panel syncs the official catalog from Steer's upstream
(always current), not from your fork. Changes you make here are ignored and will drift.

Author your own applications and dashboards under [`../my/`](../my/) instead.

| Path | What |
|------|------|
| `templates/` | Official application templates (`service.template` XML). |
| `dashboards/` | Official Grafana dashboards (JSON). |
| `logos/` | Catalog logos. |
| `catalog_index.json` | Lightweight index of the official catalog. |

> In a fresh workspace this folder may be a thin reference or a Git submodule of the upstream
> `steer-catalog`. Treat it as **read-only** either way.
