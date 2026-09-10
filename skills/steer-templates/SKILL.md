---
name: steer-templates
description: Author, validate and ship Steer application templates (service.template XML) in this workspace, from a docker-compose to a validated file under my/templates that the panel syncs and installs. Use when the user wants to add, convert, fix or publish an application template or dashboard for Steer.
---

# Steer templates

You turn an application (usually a `docker-compose.yml`) into a **Steer template**: one XML file
under `my/templates/` that the panel syncs from this repository. Read
[references/authoring-rules.md](references/authoring-rules.md) once per session; it is the
condensed contract (secrets, ports, volumes, backups, Odoo-XML gotchas).

## Workflow (GitOps plane, default)

1. **Start from the closest example**: `examples/example-stateless-app.xml` (no database) or
   `examples/example-postgres-app.xml` (database with custom backup). Never edit `steer/`.
2. **Write** `my/templates/template_<code>.xml`. One `<record model="service.template">` plus its
   sub-records (`service.template.port`, `.variable`, `.volume`, `.config.file`, `.service.config`,
   `.action`, `.repository`). Field reference: `schema/service-template.schema.json` (generated
   from the panel model; every property is a real field with its help text).
3. **Validate locally**: `python harness/validate.py my/templates/template_<code>.xml`. Fix every
   error; read the warnings (they mirror the panel lints).
4. **Validate in the panel** (renders the Jinja2 compose with real context, installs nothing):
   `python harness/validate.py --panel my/templates/template_<code>.xml` with `STEER_PANEL_URL`
   and `STEER_MCP_TOKEN` set, or call the MCP tool `validate_template` with the file content in
   `xml`.
5. **Commit and push** under `my/`. Then run `sync_template_source` (MCP; it is a proposal a
   person confirms) or wait for the daily sync. The app appears in the store.
6. **Install** with `install_catalog_template` (proposal), then deploy an instance from the panel or
   with the instance tools. Check `list_operations` / `get_operation` for the result.

## Panel-first alternative (imperative plane)

When the user wants the template created directly in the panel: call `validate_template` with a
`spec`, then `propose_template` (same spec). Nothing is saved until a person confirms. Afterwards
`export_template_xml` gives the workspace XML: commit it under `my/` so Git stays the source of
truth. Editing a template that already exists: `get_application` first, then propose with the same
`code` (system templates cannot be modified; propose a copy with another code).

## Hard rules (the validator enforces them)

- Secrets are typed (`var_type` `password`/`fernet_key`, `is_secret=True`) and referenced in the
  compose as `${VAR_NAME}`; never hard-coded.
- A web app (`is_web_app=True`) has at least one port with `traefik_routed=True`.
- A database app has `backup_mode=custom`, both `backup_script` and `restore_script`, and the raw
  DB data volume marked `exclude_from_backup=True`. The restore must verify data is present.
- `code` is unique, lowercase snake/kebab-case; `is_global`/`partner_id` are decided by the panel at
  install and ignored in the file; `display_name` on sub-records is ignored (use `description`).
- Everything in English.
