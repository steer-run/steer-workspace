# Connecting an agent or an application to a Steer panel

Every Steer panel is an **MCP server** (`POST https://<panel>/mcp`), a **REST API**
(`https://<panel>/api/v1`) and an **OAuth 2.1 authorization server** for both. All three expose
the *same* tools with the *same* permissions, confirmations and audit trail as the assistant
built into the panel. This page is for the person wiring a client or an integration; the agent
itself reads [`AGENTS.md`](../AGENTS.md).

## 1. Pick a credential

| Client | Credential | How |
|---|---|---|
| claude.ai, Claude Desktop, ChatGPT (connectors / apps) | **OAuth 2.1** (nothing to paste) | Add a custom connector with the URL `https://<panel>/mcp`, no client id or secret. The browser opens the panel's consent screen. |
| Claude Code, Codex CLI, Cursor, any MCP client with HTTP transport | **Agent token** (`stmcp_…`) | Create it in the panel: *Governance → Agent connections → New token*. Send it as `Authorization: Bearer <token>`. Claude Code can also skip the token and authorize through OAuth. |
| A conventional application (no MCP) | **Agent token** | Same token, on the REST facade `https://<panel>/api/v1`. |

An agent token is a **mask over the user it runs as**: it can never do more than that user can in
the panel, and it can be narrowed further (per-area level, environments, servers, instances, IP
allowlist, daily quota, expiration). The token is shown **once**; rotate it if you lose it, revoke
it to cut the agent off immediately.

The OAuth consent screen asks the person to choose what the agent may do (**read only**,
**read and operate**, or **full access** = everything their user can do), how long the connection
lasts and whether it reaches production. The result is an ordinary agent connection listed under
*Governance → Agent connections* (column *Via*), revocable there.

## 2. Client configuration

**Claude Code (plugin, recommended):** `/plugin marketplace add steer-run/steer-workspace` then
`/plugin install steer@steer-run`. The plugin reads `STEER_PANEL_URL` and `STEER_MCP_TOKEN` from
the environment and brings the skills `steer-templates`, `steer-operate`, `steer-troubleshoot`.

**Claude Code (no plugin):**

```bash
claude mcp add --transport http steer https://<panel>/mcp --header "Authorization: Bearer <token>"
# or, with OAuth (the browser opens the consent screen):
claude mcp add --transport http steer https://<panel>/mcp
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.steer]
url = "https://<panel>/mcp"
bearer_token_env_var = "STEER_MCP_TOKEN"
```

**Generic `mcpServers` entry** (Cursor, Claude Desktop config files, …):

```json
{ "mcpServers": { "steer": { "type": "http", "url": "https://<panel>/mcp",
  "headers": { "Authorization": "Bearer <token>" } } } }
```

**Registry manifest:** [`server.json`](../server.json) describes the remote for MCP registries
and directories (the panel host is a variable: every customer runs their own panel).

## 3. Protocol notes (MCP)

- Revision **2026-07-28** (stateless: `server/discover`, `_meta` on every request, `resultType`,
  `ttlMs`) **and** the `initialize` era (2025-03-26 … 2025-11-25). Plain JSON responses, no SSE.
- `server/discover` is public; everything else needs the token or an OAuth access token.
- Mirror headers (`MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`) are validated when present.
- `tools/list` is **filtered by what the token may do**: a read-only token sees fewer tools.
- Resources: `steer://instructions`, `steer://guide/{diagnosis,capabilities,applications,dashboards}`.
  Prompts: `troubleshoot_instance`, `troubleshoot_server`, `explain_dashboard`.
- Extensions: **Tasks** (`io.modelcontextprotocol/tasks`: `tasks/get`, `tasks/cancel`) for long
  operations; **elicitation** (MRTR) for inline confirmations.

## 4. Proposals, confirmations and long operations

Action tools (`start_instance`, `create_backup`, `deploy_instance`, `update_instance`,
`rollback_instance`, `restore_backup`, `migrate_instance`, …) **never run on their own**: they create
a **proposal**.

- If the client supports elicitation, the result is `resultType: input_required` and the retried
  call with `accept: true` runs the action **with the user's permissions**.
- Otherwise the result carries `pending_action_id` and a `confirmation_url` in the panel
  (*Governance → Agent proposals*). REST clients confirm with `POST /api/v1/proposals/<id>/confirm`.
- **Migrating an instance** is only confirmed in the panel, with the user's password, like its
  own wizard (`panel_only: true`, REST `409 CONFIRMATION_REQUIRED`).
- Confirming re-checks the token's permission for the tool that created the proposal.

**Server console.** `exec_command` runs one plain, non-interactive command on a managed server
(no pipes, redirections, `sudo` or interactive programs) but only while a **person has granted
console access** to that server in the panel (server form → *Grant console access*, or
*Governance → Console grants*): read-only for diagnosis (an allowlist of diagnostic commands: `ls`,
`cat`, `grep`, `tail`, `df`, `ps`, `ss`, `docker ps/logs`, `systemctl status`, `journalctl`…; anything
else is refused with the reason), or read and write; for a limited time and number of commands. Without a grant the tool answers so and the agent should ask the person for
one. Every command is audited with its exit code.

What the panel queues (deploy, update, restore, migration, backup) comes back as a **task**
(`resultType: task`, poll `tasks/get`) or as an `operation_id` for `get_operation` /
`list_operations`. Never retry the action call: you would start the same operation twice.

## 5. REST facade

```bash
curl -s https://<panel>/api/v1/tools -H "Authorization: Bearer <token>"
curl -s https://<panel>/api/v1/tools/get_instance -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '{"name": "odoo-prod"}'
```

| Route | Purpose |
|---|---|
| `GET /api/v1/tools` | Tools this token may call, with their JSON schema |
| `POST /api/v1/tools/<tool>` | Call a tool; body = arguments → `{ok, status, data, text}` |
| `GET /api/v1/proposals/<id>` · `POST …/confirm` · `POST …/discard` | Proposals |
| `GET /api/v1/operations[/<id>]` | Queued operations (filters `instance`, `server`, `state`, `limit`) |
| `GET /api/v1/openapi.json` | OpenAPI 3.1 contract generated from what this token sees |

Errors come as `{ok: false, error_code, message, hint, retryable}`:

| HTTP | `error_code` | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | No or invalid token (the response carries `WWW-Authenticate` with the OAuth metadata URL) |
| 403 | `PERMISSION_DENIED` / `GOVERNANCE_BLOCKED` / `FORBIDDEN` | The token mask denies it (the message names the missing permission), the kill-switch is on, or the IP is not allowed |
| 409 | `CONFIRMATION_REQUIRED` | Only confirmable in the panel (migrate) |
| 422 | `TOOL_ERROR` | A business error (bad argument, instance not found, …); read `hint` |
| 429 | `QUOTA_EXCEEDED` | Daily call limit of the token; retryable tomorrow |
| 404 | `NOT_FOUND` | Unknown tool or proposal |

A snapshot of the contract from a full-access token lives in [`api/openapi.json`](../api/openapi.json).

## 6. OAuth 2.1 details (for implementers)

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/oauth-protected-resource` (also `/mcp`, `/api/v1`) | Protected resource metadata (RFC 9728) |
| `GET /.well-known/oauth-authorization-server` | Authorization server metadata (RFC 8414); `issuer` = the panel URL |
| `POST /oauth/register` | Dynamic client registration (RFC 7591), JSON body |
| `GET /oauth/authorize` | Consent screen (panel login required) |
| `POST /oauth/token` | `authorization_code` (PKCE S256) and `refresh_token`, form-urlencoded |
| `POST /oauth/revoke` | Revoke a connection (RFC 7009) |

- Client identification: **Client ID Metadata Documents** (`client_id` = the https URL of your
  metadata document) or **dynamic registration**. Public clients (`none`) or a client secret issued
  at registration (`client_secret_post` / `client_secret_basic`).
- PKCE S256 is mandatory; `redirect_uri` must match a registered one exactly (loopback URIs match
  regardless of port); `resource` must be the panel; `iss` is returned in every authorization
  response; scopes: `steer:read`, `steer:operate`, `steer:provision` (the consent screen decides).
- Access tokens last 1 hour; refresh tokens rotate on every use. A refresh repeated within two
  minutes (parallel refreshes, a retried request) returns the same tokens; reusing an older refresh
  token revokes the connection.

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| `401` on every call | Token revoked, expired or mistyped; OAuth access token expired (refresh it) |
| `403 PERMISSION_DENIED … instance:operate` | The token mask does not grant that level for that area; edit the connection or create another token |
| `403 ip_not_allowed` | The token has an IP allowlist |
| `429 QUOTA_EXCEEDED` | Daily call limit reached |
| The action "did nothing" | It created a proposal: confirm it inline, in the panel, or through REST |
| A queued operation seems stuck | Poll `get_operation` / `tasks/get`; the panel's watchdog marks hung operations |
| claude.ai says it cannot reach the server | The panel must be reachable from the internet over HTTPS and answer `401` with `WWW-Authenticate` on `/mcp` (it does by default); check the reverse proxy |
