# Avatar-app Content Maker

## Web page

Open:

```text
https://avatar-app-vcer.onrender.com/content-maker
```

The page generates a content pack for Instagram, TikTok, and Threads:

- profile bio ideas
- content pillars
- short talking-avatar scripts
- captions
- hashtags
- weekly posting plan
- n8n automation steps

## API endpoint

```text
POST /generate-social-content/
```

Form fields:

- `project_name`
- `product`
- `audience`
- `goal`
- `offer`
- `platforms`
- `tone`
- `language`
- `post_count`
- `child_safe`

Example:

```bash
curl -X POST "https://avatar-app-vcer.onrender.com/generate-social-content/" \
  -F "project_name=Avatar-app" \
  -F "product=AI avatar and talking video generator" \
  -F "audience=people who need personal greeting videos" \
  -F "goal=registrations and first purchases" \
  -F "offer=3 free generations" \
  -F "platforms=Instagram, TikTok, Threads" \
  -F "tone=живой, простой, продающий без давления" \
  -F "language=русский" \
  -F "post_count=9" \
  -F "child_safe=false"
```

## n8n

Import `n8n_content_maker_workflow.json` into n8n.

The workflow creates a webhook:

```text
/webhook/avatar-app-content-maker
```

It sends the request to:

```text
https://avatar-app-vcer.onrender.com/generate-social-content/
```

and returns the generated JSON content pack.

## Environment

The content maker uses the existing `GEMINI_API_KEY`.

Optional:

```text
GEMINI_TEXT_MODEL=gemini-2.5-flash
```

