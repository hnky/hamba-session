# Add a demo FastMCP server to Hamba

## Instructions for the implementation session

Implement this plan, rather than producing another proposal. Read `AGENTS.md`
and relevant repository instructions first. Inspect the current application and
preserve existing functionality and uncommitted changes.

All generated application files must remain inside `blog/`. Do not deploy,
commit, or push unless separately requested.

## Goal

Add a FastMCP server to the existing Hamba blog with exactly one tool:
`add_story`.

This is for a live demo. Keep all MCP-specific implementation in one clearly
ordered module, `blog/app/mcp_server.py`. Small supporting changes to application
wiring, storage, dependencies, documentation, and tests are allowed. Do not build
a separate service or generate tools automatically from existing REST routes.

## Framework and transport

- Use the standalone `fastmcp` package, not the former SDK-bundled FastMCP.
- At planning time (September 5, 2026), the verified stable release was FastMCP
	4.0.3, supporting MCP protocol `2026-07-28` and earlier clients. Framework
	versions and protocol revisions are separate.
- Recheck stable releases and protocol support against official documentation
	before implementation. Pin the selected stable version for demo reproducibility.
	Verify APIs against that release; documentation may describe unreleased code.
- Adding FastMCP and its required dependencies is approved. Ask before adding
	unrelated dependencies.
- Check dependency compatibility first. FastMCP 4 requires Pydantic >=2.12 and
	Starlette >=1.0.1; FastAPI >=0.133.0 admits those Starlette versions. Verify the
	actual resolved environment and regression-test any required upgrades.
- Preserve the repository's existing `httpx` usage. FastMCP's HTTP stack uses
	`httpx2`; use the appropriate client and exception types in integration tests.
- Expose Streamable HTTP at `/mcp` within the existing FastAPI application.
- Combine the exported FastMCP HTTP application's lifespan with the existing
	startup/shutdown logic. Mounted sub-app lifespans do not run automatically.
- Avoid doubled endpoint paths and test trailing-slash behavior. If using a root
	mount with an internal `/mcp` route, put that mount after existing routes.
- Use stateless HTTP mode for replica compatibility. Do not depend on session
	state or an initialization handshake for authentication.
- Enable explicit trusted Host/Origin protection. Do not disable it for deployment
	or use wildcard internet hosts or permissive CORS. Only add browser CORS if needed.
- Preserve the fast, dependency-free `/health` endpoint and existing public routes.

## Single-file reading order

1. Imports, configuration, and a short explanation of the demo.
2. Custom API-key token verifier.
3. Typed story inputs and results.
4. FastMCP server setup.
5. The `add_story` tool.
6. HTTP application export.

Prefer FastMCP's supported authentication, context, validation, and transport
features over handwritten protocol or authentication plumbing. Use type hints
and async handlers; run synchronous storage work off the event loop.

## Authentication

- Accept keys created through the existing Admin API keys page, using only
	`Authorization: Bearer <key>`.
- Implement a custom FastMCP `TokenVerifier` backed by the existing repository.
	Do not use a plaintext static-token dictionary or a permissive debug verifier.
- The managed keys are distinct from legacy keys in `AUTHOR_CONFIG`.
	The existing legacy `AuthorAuth.verify_api_key()` is not a managed-key verifier.
- Add managed-key verification to the repository: validate the key format, read
	its record by key ID, compare its SHA256 hash in constant time, and reject
	missing, invalid, or revoked keys.
- Recheck storage on every HTTP request without a positive authentication cache,
	so revocation takes effect on subsequent requests. Protect discovery, tool
	listing, and tool execution, not only the write operation.
- Derive authorship from the verified key owner, who must still exist and be an
	authorized admin. Never accept the author identity or credentials as tool inputs.
- Keep verified identity request-scoped and isolated between concurrent callers.
	The tool must fail closed when invoked without authenticated request context.
- Reject malformed Bearer headers. Cookies, query parameters, and `X-API-Key`
	must not provide alternative MCP authentication.
- Return an appropriate unauthorized response with a Bearer challenge for invalid
	credentials. Fail closed with sanitized errors if key storage is unavailable.
- Never log, return, or commit raw keys. Use generated, transient credentials in
	tests; do not read or print existing secret configuration.
- Keep legacy REST API authentication unchanged.
- This is demo API-key authentication, not a full OAuth flow. Do not invent an
	OAuth issuer, discovery metadata, authorization server, or new key-issuance API.

## The `add_story` tool

Accept these required inputs:

- `slug`: the public story identifier.
- `title`: the story title.
- `lead`: the introduction.
- `published_at`: an ISO publication date.
- `story`: a nonempty list of paragraph strings.

Accept optional `source_url` and `image_url`. Do not add binary uploads or base64
image arguments. A story without an image must work with the existing placeholder.

Reuse existing story validation and storage behavior, extracting a small shared
validation helper if necessary rather than maintaining divergent rules. Enforce
bounded input sizes and retain existing image URL/download protections and limits.

Use the shared repository wrapper; never construct storage SDK clients in the MCP
module. Store the authenticated owner as the author.

Create and publish a new story. Reject duplicate slugs atomically without
overwriting existing content. A check followed by the current upsert is not
sufficient: use create-only storage semantics and equivalent concurrency protection
for the local repository. Preserve the editor's existing update behavior.

Return a structured result containing the slug, title, and public story path
(`/posts/<slug>`). Return safe validation/duplicate errors without internal details.
Describe the tool clearly as publishing immediately; use accurate write-tool
annotations and demonstrate client-side approval before execution.

Expose no editing, deletion, listing, image-upload, or key-management MCP tools.

## Supporting changes

- Add the approved dependency to `blog/requirements.txt` and adjust incompatible
	dependency constraints only as needed.
- Wire the MCP application into `blog/app/main.py` without changing public,
	author, or legacy API behavior.
- Extend `blog/app/repository.py` for managed-key verification and atomic creation.
- Update `blog/README.md` and API-key page text: managed keys now work for MCP
	`add_story`, while legacy REST authentication remains unchanged.
- Reuse existing infrastructure, identity, and storage. No new resources or
	credentials are needed. If introducing environment configuration, follow the
	repository rule to update Bicep, `azure.yaml`, and `.env.example` together.

## Verification

- Test actual HTTP discovery, `tools/list` (exactly one tool), and `tools/call`.
	In-memory MCP clients alone do not exercise HTTP authentication.
- Verify both the newest supported protocol and a legacy initialization client.
	Do not claim compatibility with a specific hosted client without testing it.
- Test missing, malformed, invalid, tampered, and revoked Bearer tokens, including
	revocation between successful requests. Test rejected alternative credentials.
- Test owner attribution, removed owners, request isolation, and storage failures.
- Test validation, optional images, successful public rendering, and duplicate
	protection including concurrent creation. Mock cloud point reads and create-only
	writes without making production requests.
- Check that keys/hashes do not appear in tool schemas, results, errors, or logs.
- Test Host/Origin protections, exact endpoint routing, and startup/shutdown across
	repeated application lifecycles.
- Run the complete existing test suite, diagnostics on changed files, and a local
	container smoke test covering `/health` and authenticated story creation.
- Keep production unchanged: no production test stories, keys, or deployments.

## Demo documentation

Document this sequence with no embedded credentials:

1. Sign in as admin and create a named API key.
2. Configure the MCP client using its secure secret-input mechanism.
3. Connect to the blog's `/mcp` endpoint using the Bearer header.
4. Discover `add_story` and approve a story creation request.
5. Open the resulting public story.
6. Revoke the key and demonstrate that subsequent requests are rejected.

## Completion report

Summarize the changed files, confirmed FastMCP/protocol versions, test results,
and local connection instructions. Clearly identify anything not verified.
Do not deploy, commit, or push without a separate request.

## Official references

- https://pypi.org/project/fastmcp/
- https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3
- https://gofastmcp.com/servers/auth/token-verification
- https://gofastmcp.com/deployment/http
- https://modelcontextprotocol.io/specification/versioning
