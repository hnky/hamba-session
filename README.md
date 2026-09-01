# Hamba session

This repository contains a prompt for rapidly generating and deploying **Hamba — Travel and stay well**.

## Open in GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/hnky/hamba-session?quickstart=1)

Create the codespace with at least the recommended 4-core machine. The development container includes:

- Python 3.12
- Docker
- Azure CLI
- Azure Developer CLI (`azd`)
- VS Code extensions for Python, Bicep, Docker, Tailwind CSS, Azure, and GitHub Copilot

## Create and deploy the blog

1. Open [prompts/create-blog.md](prompts/create-blog.md).
2. Ask GitHub Copilot to implement the prompt. The generated project will be placed in `blog/`.
3. Sign in from the terminal with `azd auth login`.
4. Change to the generated project with `cd blog`.
5. Run `azd up` to provision Azure resources and deploy the application.

Port 8000 is forwarded automatically for local FastAPI development.