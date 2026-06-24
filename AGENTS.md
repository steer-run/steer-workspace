# AGENTS.md — operating Steer from this workspace

You are an AI agent working inside a **Steer Workspace**. This file is your map: what Steer is, what
you can create, where to put it, and how to operate the panel. Read it fully before acting.

## What Steer is

Steer is an **agentic infrastructure platform** built on Odoo. From one panel it manages
Debian/Ubuntu servers with Docker and:

- **Deploys applications** as Docker Compose stacks over SSH (reverse-proxied by Traefik, with
  automatic SSL).
- **Backs up and restores** them (per-app backup/restore scripts).
- **Monitors** them (Prometheus / Grafana / Loki dashboards).
- **Exposes** them over a VPN mesh (Headscale) and manages DNS.

The unit you most often author is an **application template** (`service.template`): a declarative
description of how to deploy an app. The panel turns a template into a running **instance**
(`service.instance`).

## Where things live (read this twice)

- **You author files in [`my/`](my/) only.** `my/templates/*.xml` and `my/dashboards/*.json`.
- **Never edit [`steer/`](steer/)** — it's Steer's official catalog (read-only reference + examples).
- Your panel **syncs `my/`** from this repo. A change under `my/` reaches the panel on the next sync
  (daily, or on demand). Commits outside `my/` don't trigger anything.

## Authoring an application template

A template is an XML file with one `service.template` record plus its sub-records (ports, variables,
volumes, config files, service configs, actions). **It must validate against**
[`schema/service-template.schema.json`](schema/service-template.schema.json). Start from
[`examples/`](examples/) — copy the closest one and adapt it.

### The usual starting point: a `docker-compose`

Most apps come with a `docker-compose.yml`. Convert it like this:

1. Put the compose into `docker_compose_template` (it's Jinja2 + YAML). Replace literal secrets and
   per-instance values with variables.
2. For each **port** the app exposes, add a `service.template.port`. Mark the web port
   `traefik_routed=true` so Steer routes a subdomain to it.
3. For each **value the user sets** (DB name, admin email…) add a non-secret `service.template.variable`.
4. For each **secret** (passwords, API keys), add a variable with `var_type=password` (auto-generated)
   or `fernet_key`, and `is_secret=true`.
5. For each **bind-mount** of persistent data, add a `service.template.volume` (with `owner` and
   `exclude_from_backup`).
6. If the app has a database, set `requires_backup=true`, `backup_mode=custom`, and write
   `backup_script` / `restore_script` (see "Backups" below).

### Variables, secrets and domains — the rules that matter

- **Secrets stay secret.** A variable with `is_secret=true` (or `var_type` `password`/`fernet_key`) is
  rendered in the compose as `${VAR_NAME}` and its real value is written only to a runtime `.env`
  (mode 600) on the server — **never** inlined in the stored compose. In the compose, reference it as
  `${VAR_NAME}` where `VAR_NAME` **exactly matches** the variable `name`.
- **`password`** auto-generates a strong random password on deploy. **`fernet_key`** auto-generates a
  valid Fernet master key (use it when the deployed app is itself a panel that encrypts secrets).
- **Domains.** Use `${main_domain}` (or any `*_domain` variable) where the app needs its public URL —
  Steer resolves it to the instance's full domain at deploy. Example:
  `NEXTAUTH_URL=https://${main_domain}`.
- **Inter-variable references** resolve too: a non-secret value may reference another variable, e.g.
  `DATABASE_URL=postgresql://${db_user}:${db_password}@db:5432/${db_name}` (the `${db_password}` secret
  stays a reference for the `.env`; the rest resolves).
- Give DB-connection string variables (`db_user`, `db_name`, …) a sensible `default_value` so the app
  boots without manual input.

### Backups that actually contain the data

- **Stateless app:** `requires_backup=true`, `backup_mode=standard` (Steer tars the data volumes).
  Mark non-data volumes `exclude_from_backup=true`.
- **App with a database:** `backup_mode=custom`. Write a `backup_script` that dumps the DB
  (`pg_dump`/`mysqldump`/`mongodump`) into `$BACKUP_DATA_DIR`, and a `restore_script` that restores it
  and **verifies** the data is present (e.g. count tables > 0). **Exclude the raw DB data dir** from the
  file backup (`exclude_from_backup=true` on it) so the consistent dump is the source of truth.
- The restore must survive a **cross-restore** (restoring into a fresh instance): resolve the DB name
  from the same source the app uses.

### Health check

Set `health_check_command` to a real check that runs inside the container after deploy
(`curl -f http://localhost:PORT/health`, `pg_isready -U $POSTGRES_USER`, …). It's a soft check — it
reports, it doesn't fail the deploy.

### Odoo-XML gotchas (the file is loaded by Odoo)

- One `<odoo>` root; **no** `<data>` wrapper.
- Cross-reference Steer tags as `agz_infra_suite.tag_<name>` (e.g. `ref('agz_infra_suite.tag_self_hosted')`).
- Same-file references (a port → its template) are bare ids.
- Keep `code` unique and snake_case.

## Authoring a dashboard

A dashboard is a Grafana model JSON validated against
[`schema/monitoring-dashboard.schema.json`](schema/monitoring-dashboard.schema.json), placed in
`my/dashboards/`. The panel exposes it in the dashboards store. Start from a `steer/dashboards/` example.

## Validate before you commit (always)

```bash
python harness/validate.py my/templates/<your-app>.xml      # one file
python harness/validate.py my/                              # everything you authored
```

The validator checks the schema **and** the conventions above (secrets typed, web app has a routed
port, DB app has custom backup + excluded data dir, etc.). CI runs the same check on every push to
`my/` — a file that doesn't validate never reaches the panel.

## Operating the live panel (imperative plane)

To do things on the running panel — create an instance, deploy, check status, run a backup — use the
web services described in [`api/openapi.yaml`](api/openapi.yaml). Typical flow:

1. `GET /servers` — find the target server.
2. `POST /instances` — create an instance from a template (`code`, `server_id`, `subdomain`).
3. `POST /instances/{id}/deploy` — deploy it (stream the operation log).
4. `GET /instances/{id}/status` — confirm it's running.
5. `POST /instances/{id}/backup` — back it up.

> **Status:** the web services are **on the roadmap**; `api/openapi.yaml` is the contract they will
> implement. Treat endpoints marked `x-status: planned` as not-yet-live. The declarative plane
> (authoring files in `my/`) works today.

## Golden rules

1. Write under `my/` only. Never touch `steer/`.
2. Validate before committing.
3. Secrets are typed (`password`/`fernet_key`, `is_secret=true`) and referenced as `${VAR}` — never
   hard-coded.
4. A web app has at least one `traefik_routed` port. A DB app has a custom backup that excludes the raw
   data dir and verifies the restore.
5. Everything in English.

Questions a human can answer: [hello@steer.run](mailto:hello@steer.run).
