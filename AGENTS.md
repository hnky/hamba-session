# Hamba session

Hamba, "Travel and stay well". A FastAPI travel blog generated into `blog/`
and deployed to Azure Container Apps with `azd`. Content comes in through an
MCP server. This repo is used live on stage, so a broken `azd up` is a
broken demo.

## Repo layout
- `prompts/` the prompts that generate the app. Source of truth for scope.
- `blog/` the generated application. All app, infra and config lives here.
- `.devcontainer/` Codespaces setup

Never place generated application files outside `blog/`.

## Security
Never commit secrets. No keys, connection strings, SAS tokens or account
keys in source, templates, Bicep, tests or fixtures.
Azure access uses managed identity and RBAC. The application never holds
Azure credentials.
`.env.example` contains non-secret example settings only.
If a value is missing, add the key name and leave it empty. Never invent a
plausible looking key or connection string.

## Stack
Python 3.12, FastAPI, server-rendered Jinja templates, Tailwind CSS,
Docker, Bicep, azd. Do not add a frontend framework. Do not add an ORM.
Do not add a dependency without asking.

## Code
- Type hints on every function, `async def` for route handlers
- Storage access goes through the client wrapper, never construct an Azure
  SDK client inline in a route
- Templates own presentation, routes own data. No HTML strings in Python.
- Keep `GET /health` fast and dependency free. It is the Container Apps probe.

## Infrastructure
All infra is Bicep. `azd up` provisions and deploys in one command,
`azd deploy` ships app-only changes, `azd down` cleans up.
Nothing may require manual steps in the Azure portal.
Changing a resource name or an env var means updating Bicep, `azure.yaml`
and `.env.example` together.

## Working style
Prefer the smallest change that works. If a task has a repeatable procedure,
check `.github/skills/` before improvising.
