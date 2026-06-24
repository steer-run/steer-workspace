# Examples — golden templates to learn from

Copy the closest one into [`../my/templates/`](../my/templates/) and adapt it. Each is fully
annotated and **passes the harness** (`python ../harness/validate.py <file>`).

| File | Pattern it teaches |
|------|--------------------|
| [`example-stateless-app.xml`](example-stateless-app.xml) | A simple **stateless** web app: one routed port, a plain variable with a default, one data volume, standard backup. |
| [`example-postgres-app.xml`](example-postgres-app.xml) | A **stateful** web app backed by its own PostgreSQL: typed secrets (`${VAR}` → runtime `.env`), `${main_domain}`, inter-variable DB URL, custom `backup_script`/`restore_script`, and the raw DB data dir **excluded** from the file backup. |

These are **examples**, not part of the official catalog (their `code` starts with `example-`). Rename
the record id, `code` and `service_code` when you adapt one.

See [`../AGENTS.md`](../AGENTS.md) for the full authoring rules and
[`../schema/service-template.schema.json`](../schema/service-template.schema.json) for the field
reference.
