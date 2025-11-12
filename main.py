import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.url_reader import (
    MarkdownConversionError,
    convert_url_to_markdown,
)

# Set up logging once for the entire application.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app configuration.
app = FastAPI(title="url2markdown API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Deployment metadata (useful for health checks).
APP_VERSION = os.environ.get("APP_VERSION", "Unknown")
DEPLOYMENT_TIME = os.environ.get("DEPLOYMENT_TIME", "Unknown")
COMMIT_MESSAGE = os.environ.get("COMMIT_MESSAGE", "No commit message")


class MarkdownResponse(BaseModel):
    source_url: str
    final_url: str
    title: str | None = None
    markdown: str
    word_count: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


@app.get("/")
def read_root():
    """Simple metadata endpoint to confirm the service is running."""
    return JSONResponse(
        content={
            "app_version": APP_VERSION,
            "deployment_time": format_time(DEPLOYMENT_TIME),
            "commit_message": COMMIT_MESSAGE,
        }
    )


@app.get("/url/reader/{encoded_url:path}", response_model=MarkdownResponse)
async def url_reader(encoded_url: str):
    """
    Convert any publicly accessible URL into Markdown.
    Example call:
      GET /url/reader/https://example.com/some-article
    """
    target_url = unquote(encoded_url.strip())
    if not target_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="URL must start with http:// or https://"
        )

    try:
        result = await convert_url_to_markdown(target_url)
    except MarkdownConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return MarkdownResponse(**result.to_payload())


def format_time(time_str: str | None) -> str:
    if time_str and time_str != "Unknown":
        try:
            deploy_time = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
            deploy_time_jst = deploy_time + timedelta(hours=9)
            return deploy_time_jst.strftime("デプロイ : %-m/%-d %-H:%M")
        except ValueError:
            return time_str
    return "不明"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
