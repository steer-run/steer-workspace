#!/usr/bin/env python3
"""Steer Workspace validator.

Validate the templates and dashboards you author against the Steer schemas AND the conventions
that the panel expects. Run it before you commit — CI runs the same check on every push to `my/`.

    python harness/validate.py my/templates/my-app.xml   # one file
    python harness/validate.py my/                        # everything under a folder
    python harness/validate.py                            # defaults to ./my

Exit code 0 = all good, 1 = at least one error. Schema checks need `jsonschema`
(`pip install jsonschema`); the convention checks are pure-Python and always run.
"""
import json
import os
import re
import sys
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


def _load_schema_version():
    """Current contract version, read from the template schema's 'x-schema-version'."""
    try:
        with open(TEMPLATE_SCHEMA, encoding="utf-8") as fh:
            return json.load(fh).get("x-schema-version", "1.0")
    except Exception:
        return "1.0"


# Versión actual del contrato + las que el harness aún sabe validar. Al evolucionar el
# contrato (agregar/deprecar campos) se sube CURRENT y se mantienen acá las compatibles.
CURRENT_SCHEMA_VERSION = _load_schema_version()
SUPPORTED_SCHEMA_VERSIONS = {CURRENT_SCHEMA_VERSION}
# Marcador opcional que una plantilla puede declarar (comentario XML; Odoo lo ignora):
#   <!-- steer-schema-version: 1.0 -->
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

_BOOL = {"true": True, "false": False, "1": True, "0": False}
_INT_FIELDS = {"default_port", "sequence"}
_BOOL_FIELDS = {
    "is_web_app", "requires_database", "requires_backup", "database_is_external",
    "use_cloudflare_tunnel", "traefik_routed", "is_secret", "exclude_from_backup",
    "expose_to_host", "skip_update", "active",
}
_CHILD = {
    "service.template.port": "ports",
    "service.template.variable": "variables",
    "service.template.volume": "volumes",
    "service.template.config.file": "config_files",
}


def _coerce(field, value):
    value = (value or "").strip()
    if field in _BOOL_FIELDS:
        return _BOOL.get(value.lower(), bool(value))
    if field in _INT_FIELDS:
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _record_to_dict(rec):
    out = {}
    for f in rec.findall("field"):
        name = f.get("name")
        if not name or name == "template_id":
            continue
        if f.get("ref") is not None or f.get("eval") is not None:
            continue  # relational/eval fields (tags, fk) — skip for the logical view
        if f.get("type") == "base64" or f.get("file") is not None:
            continue  # binarios (logo 'image'): no son parte del contrato lógico
        out[name] = _coerce(name, f.text)
    return out


def parse_template_xml(path):
    """Return one logical template dict (with nested ports/variables/volumes) per XML file."""
    root = ET.parse(path).getroot()
    tmpl, children = None, {v: [] for v in _CHILD.values()}
    for rec in root.iter("record"):
        model = rec.get("model")
        if model == "service.template":
            if tmpl is not None:
                raise ValueError("more than one service.template record in the file")
            tmpl = _record_to_dict(rec)
        elif model in _CHILD:
            children[_CHILD[model]].append(_record_to_dict(rec))
    if tmpl is None:
        raise ValueError("no service.template record found")
    tmpl.update({k: v for k, v in children.items() if v})
    return tmpl

# ---------------------------------------------------------------- checks

def schema_errors(instance, schema_path):
    if not _HAVE_JSONSCHEMA:
        return []
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft202012Validator(schema)
    return ["schema: %s (at /%s)" % (e.message, "/".join(map(str, e.path)))
            for e in validator.iter_errors(instance)]


def convention_errors(t):
    """The rules the panel cares about (beyond the schema)."""
    errs, warns = [], []
    compose = t.get("docker_compose_template", "") or ""
    variables = t.get("variables", [])
    ports = t.get("ports", [])
    volumes = t.get("volumes", [])

    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", t.get("code", "")):
        errs.append("code must be lowercase snake/kebab-case")

    if t.get("is_web_app") and not any(p.get("traefik_routed") for p in ports):
        errs.append("is_web_app=True but no port has traefik_routed=True")

    if t.get("requires_database"):
        if t.get("backup_mode") != "custom":
            errs.append("requires_database=True → backup_mode must be 'custom'")
        if not t.get("backup_script") or not t.get("restore_script"):
            errs.append("requires_database=True → backup_script and restore_script are required")

    for v in variables:
        name, vtype = v.get("name", "?"), v.get("var_type")
        if vtype in ("password", "fernet_key") and not v.get("is_secret"):
            errs.append("variable '%s' is %s but is_secret is not True" % (name, vtype))
        if v.get("is_secret") and ("${%s}" % name) not in compose:
            warns.append("secret '%s' is not referenced as ${%s} in the compose" % (name, name))

    # data volume should exist if the app persists state
    if volumes and t.get("requires_database") and not any(
            v.get("exclude_from_backup") for v in volumes):
        warns.append("a DB app usually excludes the raw DB data dir from the file backup "
                     "(exclude_from_backup=True on it)")

    return errs, warns

# ---------------------------------------------------------------- driver

def validate_file(path):
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
        elif path.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
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
    target = argv[1] if len(argv) > 1 else "my"
    if not os.path.exists(target):
        print("nothing to validate at %r" % target)
        return 0
    if not _HAVE_JSONSCHEMA:
        print("note: `jsonschema` not installed — running convention checks only "
              "(pip install jsonschema for full schema validation)\n")
    total, failed, seen_codes = 0, 0, {}
    for path in iter_targets(target):
        res = validate_file(path)
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
