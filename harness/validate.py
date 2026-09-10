#!/usr/bin/env python3
"""Steer Workspace validator.

Validate the templates and dashboards you author against the Steer schemas AND the conventions
that the panel expects. Run it before you commit — CI runs the same check on every push to `my/`.

    python harness/validate.py my/templates/my-app.xml   # one file
    python harness/validate.py my/                        # everything under a folder
    python harness/validate.py                            # defaults to ./my
    python harness/validate.py --panel my/                # + the panel's own validator (see below)

Exit code 0 = all good, 1 = at least one error. Schema checks need `jsonschema`
(`pip install jsonschema`); the convention checks are pure-Python and always run.

THE SOURCE OF TRUTH IS THE PANEL. `schema/service-template.schema.json` is generated from the
panel model (every property is a real field), and the convention checks below mirror the lints of
`service.template._validation_report` in the panel. What this harness cannot do offline is render
the Jinja2 compose with the panel's context; for that, `--panel` sends each XML to your panel's
MCP endpoint (`validate_template`, nothing is installed) using STEER_PANEL_URL and STEER_MCP_TOKEN.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE_SCHEMA = os.path.join(ROOT, "schema", "service-template.schema.json")
DASHBOARD_SCHEMA = os.path.join(ROOT, "schema", "monitoring-dashboard.schema.json")

try:
    import jsonschema  # type: ignore
    _HAVE_JSONSCHEMA = True
except ImportError:
    _HAVE_JSONSCHEMA = False


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


try:
    _TEMPLATE_SCHEMA = _load_json(TEMPLATE_SCHEMA)
except Exception:  # noqa: BLE001 — a missing/broken schema is reported per file
    _TEMPLATE_SCHEMA = {}

# Versión actual del contrato + las que el harness aún sabe validar. Al evolucionar el
# contrato (agregar/deprecar campos) se sube CURRENT y se mantienen acá las compatibles.
CURRENT_SCHEMA_VERSION = _TEMPLATE_SCHEMA.get("x-schema-version", "1.1")
SUPPORTED_SCHEMA_VERSIONS = {CURRENT_SCHEMA_VERSION, "1.0"}
# Marcador opcional que una plantilla puede declarar (comentario XML; Odoo lo ignora):
#   <!-- steer-schema-version: 1.1 -->
_SCHEMA_VERSION_RE = re.compile(r"<!--\s*steer-schema-version:\s*([0-9][0-9.]*)\s*-->", re.I)


def declared_schema_version(path):
    """Versión de contrato que declara el archivo (marcador XML) o None si no declara."""
    try:
        with open(path, encoding="utf-8") as fh:
            m = _SCHEMA_VERSION_RE.search(fh.read())
        return m.group(1) if m else None
    except Exception:
        return None

# ---------------------------------------------------------------- XML → dict
# Los hijos del contrato: modelo Odoo del <record> → clave del schema. Sale del schema mismo
# ($defs), así que agregar un hijo en el panel no requiere tocar el harness.
_MODEL_OF = {
    "ports": "service.template.port",
    "variables": "service.template.variable",
    "volumes": "service.template.volume",
    "config_files": "service.template.config.file",
    "service_configs": "service.template.service.config",
    "actions": "service.template.action",
    "repositories": "service.template.repository",
}
_CHILD = {model: key for key, model in _MODEL_OF.items() if key in (_TEMPLATE_SCHEMA.get("$defs") or {})}
_BOOL = {"true": True, "false": False, "1": True, "0": False}


def _properties(model):
    """Propiedades del schema para un modelo (la plantilla o un hijo)."""
    if model == "service.template":
        return _TEMPLATE_SCHEMA.get("properties") or {}
    key = _CHILD.get(model)
    return ((_TEMPLATE_SCHEMA.get("$defs") or {}).get(key) or {}).get("properties") or {}


def _coerce(model, field, value):
    """Coerciona el texto del XML al tipo que declara el schema (como hace Odoo al importar)."""
    value = (value or "").strip()
    ftype = (_properties(model).get(field) or {}).get("type")
    if ftype == "boolean":
        return _BOOL.get(value.lower(), bool(value))
    if ftype == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if ftype == "number":
        try:
            return float(value)
        except ValueError:
            return value
    return value


# Campos que aparecen en los XML pero NO son parte del contrato lógico: la tenencia la
# decide el panel al instalar (`is_global`/`partner_id`), y `display_name` de un hijo es el
# nombre calculado de Odoo (no se persiste; usá `description`).
_IGNORED_FIELDS = {"is_global", "partner_id", "image"}
_IGNORED_CHILD_FIELDS = {"display_name"}


def _record_to_dict(rec, model):
    out = {}
    for f in rec.findall("field"):
        name = f.get("name")
        if not name or name == "template_id" or name in _IGNORED_FIELDS:
            continue
        if model != "service.template" and name in _IGNORED_CHILD_FIELDS:
            continue
        if f.get("ref") is not None:
            continue  # relational field (fk) — skip for the logical view
        ev = f.get("eval")
        if ev is not None:
            # Los booleanos/enteros se escriben a veces con eval="True"/"False"/"10"
            # (idiom Odoo). Coercionamos esos literales simples; el resto de los eval
            # (tags Command.set, refs, listas) no son parte de la vista lógica → skip.
            evs = ev.strip()
            if evs in ("True", "False"):
                out[name] = (evs == "True")
            elif re.fullmatch(r"-?\d+", evs):
                out[name] = int(evs)
            elif name == "tag_ids":
                out["tags"] = re.findall(r"ref\('steer_infra_suite\.(tag_[a-z0-9_]+)'\)", evs)
            continue
        if f.get("type") == "base64" or f.get("file") is not None:
            continue  # binarios (logo 'image'): no son parte del contrato lógico
        out[name] = _coerce(model, name, f.text)
    return out


def parse_template_xml(path):
    """Return one logical template dict (with nested children) per XML file."""
    root = ET.parse(path).getroot()
    tmpl, children = None, {v: [] for v in _CHILD.values()}
    for rec in root.iter("record"):
        model = rec.get("model")
        if model == "service.template":
            if tmpl is not None:
                raise ValueError("more than one service.template record in the file")
            tmpl = _record_to_dict(rec, model)
        elif model in _CHILD:
            children[_CHILD[model]].append(_record_to_dict(rec, model))
        elif model and model.startswith("service.template."):
            raise ValueError("unknown sub-record model %r (not in the schema)" % model)
    if tmpl is None:
        raise ValueError("no service.template record found")
    tmpl.update({k: v for k, v in children.items() if v})
    return tmpl

# ---------------------------------------------------------------- checks

def schema_errors(instance, schema_path):
    if not _HAVE_JSONSCHEMA:
        return []
    schema = _load_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    return ["schema: %s (at /%s)" % (e.message, "/".join(map(str, e.path)))
            for e in validator.iter_errors(instance)]


def convention_errors(t):
    """Mirror of the panel lints (`service.template._validation_report`), plus the schema's
    hard rules as errors so a bad file fails fast even without `jsonschema`."""
    errs, warns = [], []
    compose = t.get("docker_compose_template", "") or ""
    variables = t.get("variables", [])
    ports = t.get("ports", [])
    volumes = t.get("volumes", [])
    db_types = ("postgres", "mysql", "mongodb", "sqlserver")

    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", t.get("code", "")):
        errs.append("code must be lowercase snake/kebab-case")
    if not (compose or "").strip():
        errs.append("docker_compose_template is empty")

    # -- hard rules (the schema's allOf) --
    if t.get("is_web_app") and not t.get("use_cloudflare_tunnel") and not any(
            p.get("traefik_routed") for p in ports):
        errs.append("is_web_app=True but no port has traefik_routed=True (and no Cloudflare tunnel)")
    if t.get("requires_database"):
        if t.get("backup_mode") != "custom":
            errs.append("requires_database=True → backup_mode must be 'custom'")
        if not t.get("backup_script") or not t.get("restore_script"):
            errs.append("requires_database=True → backup_script and restore_script are required")

    # -- panel lints (warnings there, warnings here) --
    if (t.get("requires_backup") and t.get("requires_database")
            and t.get("database_type") in db_types and t.get("backup_mode") != "custom"):
        warns.append("a database app should use backup_mode=custom (dump/restore); "
                     "'standard' copies the live DB files inconsistently")
    if t.get("backup_mode") == "custom" and t.get("requires_backup") and not (t.get("backup_script") or "").strip():
        warns.append("backup_mode=custom is set but there is no backup_script")
    for v in variables:
        name, vtype = v.get("name", "?"), v.get("var_type")
        # Un var_type password/fernet_key es SIEMPRE secreto para el motor, lleve o no
        # is_secret=True explícito. Tratamos ambas formas como secreto.
        is_secret = bool(v.get("is_secret")) or vtype in ("password", "fernet_key")
        if is_secret and ("${%s}" % name) not in compose:
            warns.append("secret '%s' is not referenced as ${%s} in the compose" % (name, name))
    if volumes and t.get("requires_database") and not any(
            v.get("exclude_from_backup") for v in volumes):
        warns.append("a DB app usually excludes the raw DB data dir from the file backup "
                     "(exclude_from_backup=True on it)")
    return errs, warns

# ---------------------------------------------------------------- panel (remote)

def panel_validate(path):
    """Ask the panel's validator through MCP (`validate_template` with the XML). Nothing is
    installed: the panel imports it in a savepoint and rolls back. Returns (errors, warnings)
    or None when the panel is not configured."""
    url = (os.environ.get("STEER_PANEL_URL") or "").rstrip("/")
    token = os.environ.get("STEER_MCP_TOKEN") or ""
    if not url or not token:
        return None
    with open(path, encoding="utf-8") as fh:
        xml_text = fh.read()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "validate_template", "arguments": {"xml": xml_text},
        "_meta": {"protocolVersion": "2026-07-28", "clientCapabilities": {},
                  "clientInfo": {"name": "steer-workspace-harness", "version": "1"}}}}
    req = urllib.request.Request(
        url + "/mcp", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                 "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return ["panel: HTTP %s from %s/mcp (check STEER_MCP_TOKEN)" % (e.code, url)], []
    except (urllib.error.URLError, ValueError) as e:
        return ["panel: could not reach %s/mcp: %s" % (url, e)], []
    if "error" in data:
        return ["panel: %s" % (data["error"].get("message") or data["error"])], []
    result = data.get("result") or {}
    sc = result.get("structuredContent") or {}
    if result.get("isError") or "valid" not in sc:
        return ["panel: %s" % (sc.get("message") or (result.get("content") or [{}])[0].get("text"))], []
    errs = ["panel: %s" % e for e in sc.get("errors") or []]
    warns = ["panel: %s" % w for w in sc.get("warnings") or []]
    return errs, warns

# ---------------------------------------------------------------- driver

def validate_file(path, use_panel=False):
    rel = os.path.relpath(path, os.getcwd())
    try:
        if path.endswith(".xml"):
            t = parse_template_xml(path)
            errs = schema_errors(t, TEMPLATE_SCHEMA)
            cerrs, warns = convention_errors(t)
            errs += cerrs
            declared = declared_schema_version(path)
            if declared and declared not in SUPPORTED_SCHEMA_VERSIONS:
                errs.append(
                    "unknown contract schema version %r (this harness supports: %s). "
                    "Update the harness/schema, or fix the '<!-- steer-schema-version: ... -->' marker."
                    % (declared, ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))))
            if use_panel:
                remote = panel_validate(path)
                if remote is None:
                    errs.append("panel: set STEER_PANEL_URL and STEER_MCP_TOKEN to use --panel")
                else:
                    errs += remote[0]
                    warns += remote[1]
        elif path.endswith(".json"):
            d = _load_json(path)
            if not isinstance(d, dict) or "dashboard" not in d:
                return rel, [], []  # not a dashboard (e.g. catalog_index.json) → skip
            errs, warns = schema_errors(d, DASHBOARD_SCHEMA), []
        else:
            return None
    except Exception as e:  # noqa: BLE001 — surface any parse error as a failure
        return rel, ["could not parse: %s" % e], []
    return rel, errs, warns


def iter_targets(target):
    if os.path.isfile(target):
        yield target
        return
    for dirpath, _dirs, files in os.walk(target):
        if os.sep + ".git" in dirpath:
            continue
        for fn in sorted(files):
            if fn.endswith((".xml", ".json")):
                yield os.path.join(dirpath, fn)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    use_panel = "--panel" in argv
    target = args[0] if args else "my"
    if not os.path.exists(target):
        print("nothing to validate at %r" % target)
        return 0
    if not _TEMPLATE_SCHEMA:
        print("error: could not load %s" % TEMPLATE_SCHEMA)
        return 1
    if not _HAVE_JSONSCHEMA:
        print("note: `jsonschema` not installed — running convention checks only "
              "(pip install jsonschema for full schema validation)\n")
    total, failed, seen_codes = 0, 0, {}
    for path in iter_targets(target):
        res = validate_file(path, use_panel=use_panel)
        if res is None:
            continue
        rel, errs, warns = res
        total += 1
        # cross-file: duplicate code
        if path.endswith(".xml"):
            try:
                code = parse_template_xml(path).get("code")
                if code and code in seen_codes:
                    errs = list(errs) + ["duplicate code '%s' (also in %s)" % (code, seen_codes[code])]
                elif code:
                    seen_codes[code] = rel
            except Exception:
                pass
        if errs:
            failed += 1
            print("✗ %s" % rel)
            for e in errs:
                print("    • %s" % e)
        else:
            print("✓ %s" % rel)
        for w in warns:
            print("    ~ warning: %s" % w)
    print("\n%d checked · %d ok · %d failed" % (total, total - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
