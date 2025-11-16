import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict
from urllib.parse import unquote, urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
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
RESERVED_QUERY_PARAMS = {"markdown_only"}


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
async def url_reader(
    encoded_url: str,
    request: Request,
    markdown_only: bool = Query(
        default=False,
        description="テキストだけを返したい場合に true を指定します。",
    ),
):
    """
    Convert any publicly accessible URL into Markdown.
    Example call:
      GET /url/reader/https://example.com/some-article
    """
    target_url = _extract_target_url(encoded_url, request)
    if not target_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400, detail="URL must start with http:// or https://"
        )

    try:
        result = await convert_url_to_markdown(target_url)
    except MarkdownConversionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = result.to_payload()
    accept_header = request.headers.get("accept", "").lower()
    wants_json = (
        not markdown_only
        and accept_header
        and "application/json" in accept_header
    )
    if not wants_json:
        return PlainTextResponse(
            payload["markdown"], media_type="text/markdown; charset=utf-8"
        )

    return MarkdownResponse(**payload)


@app.get("/{raw_url:path}", include_in_schema=False)
async def root_passthrough(
    raw_url: str,
    request: Request,
    markdown_only: bool = Query(
        default=False,
        description="テキストだけを返したい場合に true を指定します。",
    ),
):
    """
    Allow requests like /https://example.com by delegating to url_reader.
    """
    if not raw_url:
        raise HTTPException(status_code=404, detail="Not Found")
    if not raw_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=404, detail="Not Found")
    return await url_reader(raw_url, request, markdown_only)


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


def _extract_target_url(encoded_url: str, request: Request) -> str:
    """
    Combine the path parameter and any non-reserved query params to rebuild the raw URL.
    This enables callers to omit URL encoding even when the target contains query strings.
    """
    trimmed = encoded_url.strip()
    if not trimmed:
        return ""
    passthrough_query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in RESERVED_QUERY_PARAMS
    ]
    if passthrough_query:
        trimmed = f"{trimmed}?{urlencode(passthrough_query, doseq=True)}"
    return unquote(trimmed)
