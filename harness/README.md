# `harness/` — validate before you commit

`validate.py` checks your templates and dashboards against the [`../schema/`](../schema/) JSON Schemas
**and** the conventions the Steer panel expects (typed secrets, web apps with a routed port, DB apps
with a custom backup that excludes the raw data dir, etc.).

```bash
python harness/validate.py my/templates/my-app.xml   # one file
python harness/validate.py my/                        # everything you authored
python harness/validate.py                            # defaults to ./my
```

Exit code `0` = all good, `1` = at least one error. CI runs the same command on every push to `my/`,
so a file that doesn't validate never reaches your panel.

## Requirements

- Python 3.8+ (standard library only for the convention checks).
- `pip install jsonschema` for full schema validation (otherwise only the convention checks run).

## What it checks

- **Schema:** required fields, valid enums (`category`, `var_type`, `database_type`, `backup_mode`),
  field types, sub-record shapes (ports/variables/volumes/config files).
- **Conventions:** `code` format and uniqueness; web apps expose a `traefik_routed` port; DB apps use
  `backup_mode=custom` with both scripts; `password`/`fernet_key` variables are marked `is_secret`;
  secrets are referenced as `${VAR}` in the compose; the DB data dir is excluded from the file backup.

> The deeper, live E2E check (deploy → backup → restore → teardown on a real server) happens **in the
> panel** — this harness is the fast, offline gate you run while authoring.
