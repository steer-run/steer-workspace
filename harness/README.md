# `harness/` — validate before you commit

`validate.py` checks your templates and dashboards against the [`../schema/`](../schema/) JSON Schemas
**and** the conventions the Steer panel expects (typed secrets, web apps with a routed port, DB apps
with a custom backup that excludes the raw data dir, etc.).

```bash
python harness/validate.py my/templates/my-app.xml   # one file
python harness/validate.py my/                        # everything you authored
python harness/validate.py                            # defaults to ./my
python harness/validate.py --panel my/                # + the panel's validator through MCP
```

Exit code `0` = all good, `1` = at least one error. CI runs the same command on every push to `my/`,
so a file that doesn't validate never reaches your panel.

## Requirements

- Python 3.8+ (standard library only for the convention checks).
- `pip install jsonschema` for full schema validation (otherwise only the convention checks run).

## What it checks

- **Schema:** required fields, valid enums (`category`, `var_type`, `database_type`, `backup_mode`),
  field types, sub-record shapes (ports, variables, volumes, config files, service configs, actions,
  repositories). The schema is **generated from the panel model** (`service.template` and its
  sub-models), so every property is a real field and unknown fields are rejected.
- **Conventions:** `code` format and uniqueness; web apps expose a `traefik_routed` port; DB apps use
  `backup_mode=custom` with both scripts; `password`/`fernet_key` variables are marked `is_secret`;
  secrets are referenced as `${VAR}` in the compose; the DB data dir is excluded from the file backup.
- **Contract version:** if a template declares the contract version it targets, the harness rejects a
  version it doesn't support (see below).
- **`--panel`:** with `STEER_PANEL_URL` and `STEER_MCP_TOKEN` set, each XML is also sent to the panel's
  `validate_template` tool (MCP). The panel imports it in a savepoint, renders the Jinja2 compose with
  its real context, runs its lints and rolls back: nothing is installed. Panel results are prefixed
  `panel:`.

## Contract versioning

The schema itself is versioned with `x-schema-version` (currently **1.1**: all seven sub-record
types, generated from the model) in
[`../schema/service-template.schema.json`](../schema/service-template.schema.json). This is the version of
the **authoring contract** — not the app's `version` label (that one is just `"latest"`, `"19.0"`, etc.).

A template **may** declare which contract version it was written against with an XML comment:

```xml
<!-- steer-schema-version: 1.1 -->
<odoo>
  <record id="template_my_app" model="service.template">
    ...
```

Odoo ignores XML comments, so the marker never affects install. The harness rejects a marker it doesn't
recognise (`SUPPORTED_SCHEMA_VERSIONS` in `validate.py`). A template with **no** marker is assumed to
target the current version. When the contract evolves (a field is added or deprecated), bump
`x-schema-version`, keep the still-validatable versions in `SUPPORTED_SCHEMA_VERSIONS`, and authors pin
their templates to the version they tested against.

> The deeper, live E2E check (deploy → backup → restore → teardown on a real server) happens **in the
> panel** — this harness is the fast, offline gate you run while authoring.
