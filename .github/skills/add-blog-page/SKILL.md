---
name: add-blog-page
description: How to add a new page or route to the Hamba FastAPI blog
---

# Adding a page to the blog

1. Route goes in `blog/app/routers/`, one module per section, registered in
   `blog/app/main.py` with `include_router`
2. Handlers are `async def` and return `templates.TemplateResponse`
3. Template goes in `blog/app/templates/`, extends `base.html`, and uses
   Tailwind utility classes only. No custom CSS files, no inline styles.
4. Blog post data comes from Table Storage through
   `blog/app/storage/posts.py`. Never query Table Storage from a route.
5. Images resolve through the Blob Storage helper and must fall back to the
   local placeholder if the blob is missing
6. Every page needs a title, a lead and a destination image. Keep the warm
   palette and the image-led layout.
7. Verify locally: `uvicorn app.main:app --reload --port 8000`,
   then check the page renders and `GET /health` still returns 200
8. New env vars must be added to Bicep, `azure.yaml` and `.env.example`
   in the same change
