# url2markdown API

FastAPI service that converts any publicly accessible URL (web pages, Notion documents, Google Docs, etc.) into clean Markdown.  
Internally it relies on the open-source `url2markdown` project (`newspaper3k` + `markdownify`) plus a few HTTP-only fallbacks for tricky, JS-heavy pages.

## Quick start

```bash
# Build & run locally
docker compose up --build

# or run directly on host (requires Python 3.9+)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Deploying to Vercel

The repo already contains `vercel.json` plus a serverless entry point under `api/index.py` that imports the FastAPI app from `main.py`. Deploy with the standard Vercel workflow:

```bash
npm i -g vercel          # once
vercel login             # once per machine
vercel link              # run inside this repo to bind the Vercel project
vercel deploy --prod     # builds and uploads the FastAPI serverless function
```

You can also run `vercel dev` locally to emulate Vercel’s router; every request hits the same FastAPI routes as in Docker.

## API

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/url/reader/{target_url}` | Returns Markdown for the provided URL. Use the full URL after the path segment (FastAPI captures the rest of the path). |

Example request:

```
GET /url/reader/https://www.notion.so/dify-Aimsales-2a99c708e4d880159321d1f2f87f64a3?source=copy_link
```

Example response (trimmed):

```json
{
  "source_url": "https://www.notion.so/dify-Aimsales-…",
  "final_url": "https://www.notion.so/dify-Aimsales-…?pvs=4",
  "title": "【dify読み込み用】Aimsales概要",
  "word_count": 240,
  "metadata": {
    "normalizer": "notion-reader-mode",
    "renderer": "notion-api"
  },
  "markdown": "# Heading…"
}
```

## How it works

- **url2markdown pipeline** – Uses `newspaper3k` for article extraction and `markdownify` to transform the cleaned HTML into Markdown.
- **HTML sanitizing** – Removes scripts, styles, nav/footer blocks, forms, and other boilerplate before conversion.
- **Dynamic rendering** – Everything now stays HTTP-only: Notion pages are fetched via the public `notion-api.splitbee.io` proxy, Google Docs are rewritten to their `export?format=html` endpoint, and any stubborn page falls back to `https://r.jina.ai/<original_url>` for a readable snapshot before converting to Markdown.
- **Special URL handling** – Google Docs links are transparently rewritten to their `export?format=html` endpoint. Notion links get `?pvs=4` appended for a print-friendly view.

## Testing locally

```bash
# Simple smoke test against example.com
python - <<'PY'
import asyncio
from services.url_reader import convert_url_to_markdown
async def main():
    result = await convert_url_to_markdown("https://example.com")
    print(result.title, result.word_count)
asyncio.run(main())
PY
```

For manual API testing, run the server and hit `http://localhost:8000/docs` to try the interactive Swagger UI.
