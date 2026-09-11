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
volumes, config files, service configs, actions, repositories). **It must validate against**
[`schema/service-template.schema.json`](schema/service-template.schema.json), which is **generated
from the panel model**: every property is a real field with its help text, and unknown fields are
rejected. Start from [`examples/`](examples/) — copy the closest one and adapt it. Two fields you
will see in the official catalog are not part of the contract: `is_global` (tenancy is decided by
the panel at install) and `display_name` on sub-records (Odoo's computed name; use `description`).

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
- Cross-reference Steer tags as `steer_infra_suite.tag_<name>` (e.g. `ref('steer_infra_suite.tag_self_hosted')`).
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
python harness/validate.py --panel my/                      # + the panel's own validator (renders the compose)
```

The validator checks the schema **and** the conventions above (secrets typed, web app has a routed
port, DB app has custom backup + excluded data dir, etc.); they mirror the panel's lints. With
`--panel` (and `STEER_PANEL_URL` / `STEER_MCP_TOKEN` set) each file is also validated by the panel
itself through MCP (`validate_template`): it renders the Jinja2 compose with real context and
installs nothing. CI runs the offline check on every push to `my/` — a file that doesn't validate
never reaches the panel.

## Operating the live panel (imperative plane): MCP

The panel **is** an MCP server (`POST https://<your-panel>/mcp`, spec 2026-07-28, also the
`initialize` era). Every tool runs with the permissions of the user behind the token and is
audited; writes never run directly, they create a **proposal** a person confirms (inline when
your client supports elicitation, or through a confirmation URL).

**Connect.** Create a token in the panel (*Governance → Agent connections*), then (the
full guide for the person doing the wiring, error codes included, is
[`docs/connect.md`](docs/connect.md)):

- **Claude Code, plugin (recommended):** `/plugin marketplace add steer-run/steer-workspace` then
  `/plugin install steer@steer-run`. It brings the MCP server (reads `STEER_PANEL_URL` and
  `STEER_MCP_TOKEN` from your environment) and the skills `steer-templates`, `steer-operate`,
  `steer-troubleshoot`. Opening this repository in Claude Code also offers the same server from
  `.mcp.json`.
- **Claude Code, no plugin:** `claude mcp add --transport http steer https://<panel>/mcp --header
  "Authorization: Bearer <token>"`.
- **Codex CLI:** in `~/.codex/config.toml`:
  ```toml
  [mcp_servers.steer]
  url = "https://<panel>/mcp"
  bearer_token_env_var = "STEER_MCP_TOKEN"
  ```
  The skills are also exposed under `.agents/skills/` for Codex.
- **Anything else that speaks MCP:** HTTP transport, `Authorization: Bearer <token>`.
- **claude.ai, ChatGPT, or any client that does OAuth (no token to paste):** add the panel as a
  custom connector with the URL `https://<panel>/mcp`, no client id or secret. The panel is its own
  OAuth 2.1 authorization server (RFC 9728 / 8414 discovery, Client ID Metadata Documents and dynamic
  registration, PKCE S256, rotated refresh tokens). The browser lands on the panel's consent screen:
  log in, see which client asks and where it returns to, and choose what the agent may do (read only,
  read and operate, or full access), how long the connection lasts and whether it reaches production.
  The result is a normal agent connection (*Governance → Agent connections*), revocable there.

**Discover.** Call `steer_help` (tools by intent, what your token grants) or `get_overview`.
Read the resources `steer://instructions`, `steer://guide/applications`,
`steer://guide/diagnosis`; use the prompts `troubleshoot_instance` / `troubleshoot_server`.

**Templates, both planes.**

| Step | Tool |
|------|------|
| Check a spec, an installed app or a workspace XML with the panel's validator (installs nothing) | `validate_template` (`spec` / `code` / `xml`) — also `python harness/validate.py --panel` |
| Create or modify a template in the panel (proposal) | `propose_template` |
| Get the workspace XML of an installed template, to commit it under `my/` | `export_template_xml` |
| See the store and install an app from it (proposal) | `list_catalog`, `install_catalog_template` |
| Pull your repository into the panel now (proposal) | `sync_template_source` |
| Installed templates | `list_applications`, `get_application` |

**Operate.** `list_instances` → `get_instance` → `diagnose_instance` → containers / logs →
`start_instance` / `stop_instance` / `restart_instance` / `create_backup` (proposals). Long
operations return a task (`tasks/get`) or an `operation_id` (`get_operation`).

**Provision.** `get_deploy_schema` → `validate_deploy` (dry run with the real wizard rules) →
`deploy_instance` (proposal → task). On a deployed instance: `update_instance`, `rollback_instance`
(`list_instance_snapshots`), `restore_backup` (`list_backups`), `migrate_instance` (panel-only
confirmation). Stale state: `check_instance_state`, `test_server_connection`. **Console:**
`exec_command` runs one plain command on a server (no pipes, `sudo` or interactive programs)
only while a person keeps a console grant on that server; if the tool says there is no grant,
ask the person to grant it from the server form and do not try to work around it.

> **REST:** the same tool registry is also served as a plain REST facade for conventional
> applications: `POST $STEER_PANEL_URL/api/v1/tools/<tool>` with the tool arguments as the JSON
> body, same bearer token, same permissions and audit. Actions come back as a proposal
> (`status: awaiting_confirmation`) to confirm with `POST /api/v1/proposals/<id>/confirm` (or in
> the panel); long operations return an `operation_id` for `GET /api/v1/operations/<id>`. The
> contract is generated by the panel itself at `GET /api/v1/openapi.json` (only the tools your
> token can call); `api/openapi.json` here is a snapshot from a full-access token. Agents should
> prefer MCP.

## Golden rules

1. Write under `my/` only. Never touch `steer/`.
2. Validate before committing.
3. Secrets are typed (`password`/`fernet_key`, `is_secret=true`) and referenced as `${VAR}` — never
   hard-coded.
4. A web app has at least one `traefik_routed` port. A DB app has a custom backup that excludes the raw
   data dir and verifies the restore.
5. Everything in English.

Questions a human can answer: [hello@steer.run](mailto:hello@steer.run).
