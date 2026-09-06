# Add full article retrieval to the Hamba MCP server

## Instructions for the implementation session

Implement this change, rather than producing another proposal. Read `AGENTS.md`,
`prompts/add-mcp.md`, and `prompts/list-articles.md` for context. Inspect the current
implementation and preserve existing functionality and uncommitted changes. This
prompt extends the earlier tool scope; do not remove or recreate existing tools.

All generated application files must remain inside `blog/`. Do not add dependencies,
deploy, commit, or push unless separately requested.

Keep the live-demo workflow short: do not create or run automated tests, regression
suites, or smoke tests unless separately requested. Do not make cloud storage
requests or create production content during implementation.

## Goal

Add a third authenticated MCP tool named `get_article`. It retrieves the full
published article for a slug discovered through `list_articles`, so an MCP client
can read existing content before deciding whether to publish another story.

Keep `add_story` and `list_articles` unchanged, including their input and output
schemas. In particular, `list_articles` must remain a compact summary listing.

Keep MCP-specific implementation in `blog/app/mcp_server.py`. Reuse the existing
repository wrapper and `/mcp` Streamable HTTP transport. Do not add a REST endpoint,
separate service, infrastructure, environment settings, or direct Azure SDK access.

## Tool contract

`get_article` accepts exactly one required argument:

- `slug`: the public article identifier. Reuse the existing `Slug` type and its
  length and lowercase hyphen-separated format constraints. Describe it as a slug
  returned by `list_articles`, not a URL or storage key.

Return a typed Pydantic `GetArticleResult` object with exactly these fields at the
top level (no additional `article` wrapper):

- `slug`: string
- `title`: string
- `lead`: string
- `published_at`: string, preserving the stored publication date
- `author`: string, defaulting to `""` when missing or null in older content
- `path`: string, formatted as `/posts/<slug>`
- `source_url`: string, defaulting to `""` when missing or null
- `story`: the complete ordered list of paragraph strings

Return stored Hamba content without summarizing, truncating, rewriting, or rendering
paragraphs as HTML. Do not fetch or scrape `source_url`; full article means the full
story stored by Hamba, not the original article on an external website.

Build the result using an explicit field allowlist. Do not return image storage
names, image source URLs, storage partition/row keys, credentials, hashes, API-key
metadata, or any other internal fields. Do not serialize a raw repository record.
Keep the output schema explicit and stable without changing existing result models.

Describe the tool as retrieving one full published Hamba article by slug. Set:

- `readOnlyHint=True`
- `destructiveHint=False`
- `idempotentHint=True`
- `openWorldHint=False`

## Storage, authentication, and errors

- Read the article through the existing `posts.get_post(slug)` repository method;
  do not list and scan all articles. Run the synchronous read off the event loop
  using the existing threadpool pattern.
- Only expose published content. Preserve the repository's published-content
  boundary and do not introduce access to other storage partitions.
- If no article exists, return a short MCP `ToolError`, such as
  `Article not found.` Do not return a successful empty object or fallback story.
- Fail closed on storage or result-construction failures. Log internal details
  server-side without key material and return a short sanitized error, such as
  `The article could not be retrieved. Please try again.` Do not expose exception
  messages, Azure details, or credentials. Keep not-found errors distinct from
  storage failures.
- Use the existing managed API-key authentication and request-scoped identity.
  Require a current admin owner and fail closed without authenticated context.
- Extend verified token scopes to cover `add_story`, `list_articles`, and
  `get_article`. Preserve immediate revocation checks and request isolation.
- Keep Bearer-header rules, Host/Origin protection, stateless HTTP mode, endpoint
  routing, application lifespan, public routes, and `/health` unchanged.
- Managed MCP keys remain separate from legacy REST API keys.

## Documentation

Update `blog/README.md`, the Admin API keys page, and MCP server instructions to
describe all three tools. Replace wording that says there are exactly two tools.
Make clear that `list_articles` and `get_article` are read-only; only `add_story`
publishes immediately and requires client-side approval.

Document the client sequence: call `list_articles`, pass a returned `slug` to
`get_article`, read its `story`, and optionally approve a new `add_story` call.
Use no embedded credentials and do not execute the sequence during implementation.

## Completion report

Briefly summarize the changed files and the final `get_article` input/output
schema. Clearly identify anything not verified. Do not run tests or deploy,
commit, or push without a separate request.