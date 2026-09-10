# Authoring rules (condensed from AGENTS.md)

## From a docker-compose to a template

1. Put the compose into `docker_compose_template` (Jinja2 + YAML). Replace literal secrets and
   per-instance values with variables. Available context: `{{ INSTANCE_CODE }}`, `{{ PORT_<CODE> }}`
   for each port, every variable by name, `${main_domain}` (public domain at deploy).
2. Each exposed port → `service.template.port` (`code` snake_case, `default_port`,
   `traefik_routed=True` on the web port, `traefik_path_prefix` for sub-paths like `/websocket`).
3. Each user-settable value → `service.template.variable` (`name`, `var_type`, `default_value`,
   `is_required`). Give DB-connection variables sensible defaults so the app boots unattended.
4. Each secret → `service.template.variable` with `var_type=password` (auto-generated) or
   `fernet_key`, `is_secret=True`; reference it as `${NAME}` in the compose. Its value lands only
   in the runtime `.env` (mode 600) on the server.
5. Each persistent bind-mount → `service.template.volume` (`local_path` starts with `./`, `owner`
   `UID:GID`, `exclude_from_backup` on raw DB data dirs).
6. Rendered config files → `service.template.config.file` (`filename`, `path` starting with `./`,
   `content_template` Jinja2, `is_executable` for hook scripts, `skip_update` for first-deploy-only).
7. Resource limits / logging per compose service → `service.template.service.config`
   (`service_name`, `memory_limit`, `cpu_limit`, `restart_policy`...).
8. Optional maintenance buttons → `service.template.action` (`code`, `name`, `command` run in
   `target_service`, `requires_confirmation`, `backup_before`).

## Backups

- Stateless app: `requires_backup=True`, `backup_mode=standard` (Steer tars the data volumes).
- Database app: `backup_mode=custom`; `backup_script` dumps into `$BACKUP_DATA_DIR` running the
  dump **inside** the DB container (`docker compose exec -T db ...`); `restore_script` brings the DB
  up, restores from `$RESTORE_DATA_DIR` and **verifies** (e.g. counts tables > 0). Exclude the raw
  DB directory from the file backup.
- The restore must survive a cross-restore into a fresh instance: resolve names from the same
  variables the app uses, never from hard-coded instance codes.

## Health check

`health_check_command` runs inside the container after deploy (soft check): `curl -fsS
http://localhost:PORT/health || exit 1`, `pg_isready -U $POSTGRES_USER`, etc.

## Odoo-XML gotchas

- One `<odoo>` root, no `<data>` wrapper. One `service.template` record per file.
- Sub-records reference the template with `<field name="template_id" ref="template_<code>"/>`.
- Tags: `<field name="tag_ids" eval="[Command.set([ref('steer_infra_suite.tag_self_hosted')])]"/>`.
- Booleans as text `True`/`False`; long text (compose, scripts) inside `<![CDATA[ ... ]]>`.
- Optional contract marker as the first comment: `<!-- steer-schema-version: 1.1 -->`.
