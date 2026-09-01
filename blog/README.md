# Hamba

**Hamba — Travel and stay well** is a server-rendered FastAPI travel blog designed for a polished live demo. It uses Tailwind CSS, Azure Table Storage for posts, Azure Blob Storage for destination images, and Azure Container Apps for hosting.

## Architecture

- FastAPI and Jinja templates render the website.
- Azure Table Storage contains post metadata and story content.
- Azure Blob Storage contains one destination image per post; the application streams private blobs through its managed identity.
- Azure Container Registry stores the Docker image.
- Azure Container Apps runs the image with readiness and liveness probes on `GET /health`.
- A user-assigned managed identity receives only Blob Data Contributor, Table Data Contributor, and ACR Pull roles. No storage keys or Azure credentials are stored by the application.

On cloud startup, the application seeds ten original English summaries based on attributed Hamba.nl magazine stories and downloads one associated image per story into the private Blob container. Stale seed rows are removed. If an image download or Blob read fails, a bundled SVG placeholder is shown.

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

Azure deployment settings are injected by Bicep. For optional local Azure Storage access, copy `.env.example` to `.env`, authenticate with `az login`, and export the values into your shell. The example file contains no secrets.

| Setting | Purpose |
|---|---|
| `AZURE_STORAGE_BLOB_URL` | Blob service endpoint |
| `AZURE_STORAGE_TABLE_URL` | Table service endpoint |
| `AZURE_STORAGE_BLOB_CONTAINER` | Image container, defaults to `images` |
| `AZURE_STORAGE_TABLE_NAME` | Posts table, defaults to `posts` |

## Cleanup

Remove all Azure resources created for the environment:

```bash
azd down --purge
```

Review the prompt carefully before confirming deletion.
