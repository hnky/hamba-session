# Add article listing to the Hamba MCP server

## Instructions for the implementation session

Implement this change, rather than producing another proposal. Read `AGENTS.md`,
`prompts/add-mcp.md`, and the relevant repository instructions first. Inspect the
current implementation and preserve existing functionality and uncommitted changes.

All generated application files must remain inside `blog/`. Do not deploy, commit,
or push unless separately requested. Do not add dependencies for this change.

## Goal

Extend the existing authenticated FastMCP server with a second tool named
`list_articles`. Keep the existing `add_story` tool unchanged. The new tool gives
an MCP client a compact list of published Hamba articles so the client can discover
existing content before deciding whether to publish another story.

Keep MCP-specific implementation in `blog/app/mcp_server.py`. Reuse the existing
repository wrapper and HTTP transport; do not add a REST endpoint, a separate
service, or direct Azure SDK access from the MCP module.

## Tool contract

`list_articles` takes no arguments and returns a structured object containing an
`articles` array. Each article must contain only these public summary fields:

- `slug`
- `title`
- `lead`
- `published_at`
- `author`, using an empty string when older seeded content has no author
- `path`, formatted as `/posts/<slug>`
- `source_url`, using an empty string when absent

Do not return full story paragraphs, image storage names, image source URLs,
storage partition/row keys, credentials, key metadata, or other internal fields.
Use typed Pydantic result models so the MCP schema and structured response are
explicit and stable.

Return every published article in the repository's existing order, newest first.
Do not add pagination, filtering, search, or sorting inputs in this change. An empty
repository must return `{ "articles": [] }` rather than an error.

Describe the tool as listing public article summaries. Set accurate tool annotations:
it is read-only, non-destructive, idempotent, and does not interact with external
systems beyond the Hamba service's own storage.

## Authentication and errors

- Protect `list_articles` with the existing managed API-key authentication used by
  MCP discovery and `add_story`; do not make it anonymously accessible.
- Update the verified token scopes so they accurately cover both MCP tools. Keep
  request-scoped identity, immediate revocation checks, and admin-only access.
- Run synchronous repository reads off the event loop.
- Fail closed if storage is unavailable. Log internal details server-side and return
  a short sanitized tool error without Azure details, credentials, or key material.
- Keep the existing Bearer-header rules, Host/Origin protection, stateless HTTP
  mode, endpoint path, and application lifespan behavior unchanged.

## Documentation

Update `blog/README.md` and the Admin API keys page to state that managed keys can
use both `add_story` and `list_articles`. Update wording that says the MCP server
has exactly one tool. Keep the distinction between managed MCP keys and legacy REST
API keys clear.

## Verification

- Update MCP HTTP discovery and `tools/list` tests to require exactly
  `add_story` and `list_articles`, including the read-only annotations.
- Call `list_articles` through the actual `/mcp` Streamable HTTP endpoint and verify
  its structured response, newest-first order, public paths, missing optional-field
  defaults, and empty repository behavior.
- Verify that story bodies, image/storage fields, credentials, hashes, and API-key
  metadata do not appear in the tool schema or result.
- Test a repository read failure and confirm the returned error is sanitized.
- Preserve tests for authentication, revocation, owner isolation, protocol versions,
  endpoint routing, repeated lifecycles, `add_story`, public routes, and `/health`.
- Run the complete test suite and diagnostics for changed files. Do not make cloud
  storage requests, create production content, or deploy.

## Completion report

Summarize the changed files, the final schemas for both MCP tools, and test results.
Clearly identify anything not verified. Do not deploy, commit, or push without a
separate request.