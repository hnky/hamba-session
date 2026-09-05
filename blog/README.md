# Hamba

**Hamba — Travel and stay well** is a server-rendered FastAPI travel blog designed for a polished live demo. It uses Tailwind CSS, Azure Table Storage for posts, Azure Blob Storage for destination images, and Azure Container Apps for hosting.

## Architecture

- FastAPI and Jinja templates render the website.
- Azure Table Storage contains post metadata and story content.
- Azure Blob Storage contains one destination image per post; the application streams private blobs through its managed identity.
- Azure Container Registry stores the Docker image.
- Azure Container Apps runs the image with readiness and liveness probes on `GET /health`.
- A user-assigned managed identity receives only Blob Data Contributor, Table Data Contributor, and ACR Pull roles. No storage keys or Azure credentials are stored by the application.

On cloud startup, the application seeds missing stories from ten original English summaries based on attributed Hamba.nl magazine stories and downloads one associated image per new story into the private Blob container. Existing stories and author edits are never overwritten by startup seeding. If an image download or Blob read fails, a bundled SVG placeholder is shown.

## Local development

Prerequisites: Python 3.12+ and Docker (optional).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. Without Azure Storage environment variables, bundled sample content and local image fallbacks are used.

Run tests:

```bash
pytest
```

Build and run the container:

```bash
docker build -t hamba .
docker run --rm -p 8000:8000 hamba
```

## Deploy to Azure

Prerequisites: Azure CLI and Azure Developer CLI (`azd`), with permission to create resources and role assignments in the target subscription.

Authenticate and deploy everything with one command flow:

```bash
azd auth login
azd up
```

`azd up` prompts for an environment name, subscription, and Azure region, then provisions the resource group, Storage account, ACR, Log Analytics workspace, managed identity, Container Apps environment, RBAC assignments, and the application.

For application-only updates:

```bash
azd deploy
```

Check the deployed health endpoint at `<SERVICE_WEB_URI>/health` or retrieve the URL with:

```bash
azd env get-value SERVICE_WEB_URI
```

## Configuration

### Author login and editing

Open `/author/login` (also linked in the footer). Signed-in authors can list,
create, and edit all published stories at `/author/posts`. Saving publishes
immediately. Drag a destination image into the editor or use its file picker;
JPEG, PNG, and WebP files up to 8 MB and 20 megapixels are supported, with a
preview and remove button. Images are optional: new stories without an image
use the default placeholder. Alternatively, enter a public image URL. Uploaded
files take priority over URLs, are checked by decoding the image, and are
re-encoded as JPEG to strip metadata (transparent areas become white).
Files are saved through the storage wrapper to private Azure Blob Storage in
production, or in memory locally. Unique upload names prevent stale cached
images after replacement. If form validation fails, text is retained but the
file must be selected again. Editing can leave both image inputs empty to keep
the existing image. Slugs cannot change.
All configured authors have editor access to all stories.

For local development, generate an ignored configuration file from the `blog/`
directory:

```bash
python -m scripts.create_author_config --local
```

This prompts for a username and password, permits a weak **local-only** demo
password, and writes `.author-config.json` with owner-only permissions. It is
excluded from Git and Docker builds. The app reads this file only when
`AUTHOR_CONFIG` is unset and it is not running in Azure Container Apps or using
Azure Table Storage. Restart the local server after changing credentials.
To regenerate local credentials, remove the ignored configuration file first.
Local stories/images are in-memory and reset when the process restarts.

For production, use `python -m scripts.create_author_config` without `--local`.
It requires a password of at least 12 characters and generates a random session
secret, password hash, and API-key hash. Store the resulting `AUTHOR_CONFIG`
securely in the deployment environment; never commit it. The optional secure
Bicep parameter maps it to a Container Apps secret, not a plain environment
value. Empty/unset production configuration disables login—there is no default
production account. Rotating the configuration and deploying a new revision
invalidates previous sessions. Credential/configuration changes require
provisioning (`azd provision --preview`, then `azd up`); `azd deploy` alone only
updates application code. Keep `AUTHOR_CONFIG` available for future provisioning
so it is not reset to empty.

Browser sessions use signed eight-hour cookies (`HttpOnly`, `SameSite=Lax`,
`Secure` on HTTPS), and editing/logout forms require a session CSRF token.
The `/api/author/posts` endpoints require each author's `X-API-Key`; browser
cookies alone do not authorize API requests. Password changes currently happen
through configuration, not through a web password-change page.

### Admin API key management

The account named `admin` can open **Author studio → API keys** at
`/author/api-keys` to create named keys, view their public identifiers and
creation dates, and revoke them. Other author accounts cannot manage keys.
Creation and revocation require a signed browser session and a CSRF token.

Each key contains 32 cryptographically random secret bytes and a unique ID.
The complete key is shown only in the creation response (marked `no-store`);
copy it into a password manager before leaving. There is no retrieval endpoint.
Only a SHA-256 hash, public identifier, name, creator, and creation/revocation
timestamps are persisted. Keys are stored in the `api-keys` partition of the
existing posts table, accessed via managed identity; no extra infrastructure or
configuration is needed. Locally they are in memory and reset on restart.
Revocation is permanent; create a new key to replace a revoked or lost key.

**Scope:** this implements key management only. Newly managed keys are not
connected to any API authentication yet and grant no API access. Existing
legacy API endpoints and their `AUTHOR_CONFIG` authentication are unchanged;
their keys are not listed or revoked by this page. Future API integration must
check the stored hash and revocation state on every request. Keep full keys
out of source control, logs, URLs, and chat.

Azure deployment settings are injected by Bicep. For optional local Azure Storage access, copy `.env.example` to `.env`, authenticate with `az login`, and export the values into your shell. The example file contains no secrets.

| Setting | Purpose |
|---|---|
| `AZURE_STORAGE_BLOB_URL` | Blob service endpoint |
| `AZURE_STORAGE_TABLE_URL` | Table service endpoint |
| `AZURE_STORAGE_BLOB_CONTAINER` | Image container, defaults to `images` |
| `AZURE_STORAGE_TABLE_NAME` | Posts table, defaults to `posts` |
| `AUTHOR_CONFIG` | Optional sensitive author configuration; keep empty in example files |

## Cleanup

Remove all Azure resources created for the environment:

```bash
azd down --purge
```

Review the prompt carefully before confirming deletion.
