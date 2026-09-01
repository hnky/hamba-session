# Create a modern travel blog

Build a small, polished travel blog called **Hamba**, with the tagline **Travel and stay well**, that can be generated and deployed quickly for a live presentation. Give it an inspiring, image-led design with a warm color palette, large destination photography, and clear typography.

## Project location

- Create the complete project inside a new `blog/` folder at the repository root
- Keep all application, infrastructure, configuration, and documentation files inside `blog/`
- Do not modify or place generated application files outside `blog/`

## Pages

- Homepage with a travel-themed hero section and a responsive grid of published trips
- Blog detail page for each destination
- Each travel post has exactly one destination image, a title, lead, story content, and publication date
- Include at least three realistic sample travel posts for different destinations so the website looks complete immediately after deployment
- Use freely accessible placeholder destination images and gracefully fall back to a local placeholder if an image cannot be loaded

## Application stack

- Python with FastAPI
- Server-rendered HTML templates
- Tailwind CSS for a modern, responsive interface
- Docker
- Include a `GET /health` endpoint that returns HTTP 200 and a small JSON response

## Azure infrastructure

- Azure Blob Storage for blog images
- Azure Table Storage for blog post data
- Azure Container Registry for the application image
- Azure Container Apps for hosting the application
- Use managed identity and RBAC where possible; do not store Azure credentials in the application
- Define all infrastructure as code with Bicep

## Deployment

- Use Azure Developer CLI (`azd`)
- The complete application and infrastructure must deploy with one command: `azd up`
- Application-only updates must deploy with `azd deploy`
- Do not require manual configuration in the Azure portal
- Configure the Container Apps health probe to use `GET /health`

## Deliverables

- Complete application source code
- Dockerfile
- Bicep infrastructure files
- `azure.yaml` configuration
- `.env.example` containing only non-secret example settings
- README with local development, `azd up`, `azd deploy`, and cleanup (`azd down`) instructions

