# Steer Workspace

Your **agent-ready workspace** for [Steer](https://steer.run) — the agentic infrastructure
platform. Clone it, point an AI at it, and you can author your own applications and dashboards,
keep them versioned in Git, and operate your Steer panel end to end.

> **You steer. It runs.**

This repository is a **GitHub template**. Click **"Use this template"** to create your own private
copy, then connect it to your Steer panel.

## What's inside

| Path | What it is | Who edits it |
|------|------------|--------------|
| [`steer/`](steer/) | Steer's **official catalog** (templates + dashboards) — reference & global source. | Steer (read-only for you) |
| [`my/`](my/) | **Your** applications and dashboards. This is the folder your panel syncs. | **You / your AI** |
| [`schema/`](schema/) | Machine-readable JSON Schemas. They keep the AI from inventing fields. | Steer |
| [`api/`](api/) | The OpenAPI contract of the panel's web services (operate the panel from an agent). | Steer |
| [`harness/`](harness/) | Local validators — check what you author **before** you commit. | Steer |
| [`examples/`](examples/) | Golden, annotated examples to learn from. | Steer |
| [`AGENTS.md`](AGENTS.md) | **The map.** What this is and how to operate Steer. The first thing an AI should read. | Steer |

## The two ways an AI works here

1. **Declarative (GitOps).** The AI writes **files** — templates and dashboards — into `my/`. Your
   Steer panel **syncs** that folder (once a day, or on demand) and they show up in your catalog,
   ready to deploy. You never edit `steer/`.
2. **Imperative (API).** The AI **operates the live panel** through web services described in
   [`api/openapi.yaml`](api/openapi.yaml): create instances, deploy, check status, run backups.

## Quick start

1. **Use this template** → create your repo under your account/org.
2. **Connect it to Steer:** in your panel, go to *Applications → Template Sources*, add a **GitHub**
   source pointing at your repo (HTTPS token), with templates path `my/templates` and dashboards path
   `my/dashboards`.
3. **Point your AI at this repo.** Tell it to read [`AGENTS.md`](AGENTS.md). Then ask it things like:
   - *"Create a template for [app] from this docker-compose."*
   - *"Add a dashboard that tracks [metric]."*
   - *"Deploy my `n8n` app to the `prod` server and show me its status."*
4. **Validate before you commit:** `python harness/validate.py my/templates/<your-app>.xml`
5. **Commit & push.** Your panel picks it up on the next sync.

## Conventions

- **Everything here is in English** (this workspace is public and AI-facing).
- Your own apps live under `my/` — **never** under `steer/`.
- Templates and dashboards must validate against the schemas in [`schema/`](schema/).

---

Questions: [hello@steer.run](mailto:hello@steer.run) · [steer.run](https://steer.run)
