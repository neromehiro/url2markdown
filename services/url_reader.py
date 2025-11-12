from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qsl, urlparse, urlunparse, urlencode

import httpx
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify as markdownify_html
from url2markdown.downloader import downloader as url2markdown_downloader

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}

UNWANTED_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "form",
    "button",
    "input",
    "video",
    "audio",
}

UNWANTED_SELECTORS = [
    "header",
    "footer",
    "nav",
    "[role='navigation']",
    "[aria-hidden='true']",
    ".notion-topbar",
    ".notion-sidebar-container",
    ".notion-record-navbar",
    ".kix-paginateddocumentheader",
    ".kix-paginateddocumentfooter",
]

MAIN_CONTENT_SELECTORS = [
    ".notion-page-content",
    ".notion-page-block",
    ".kix-appview-editor",
    ".kix-zoomdocumentplugin-mobile-view",
    "#contents",
    "#doc-contents",
    "article",
    "main",
    "[role='main']",
]

GOOGLE_DOCS_RE = re.compile(r"(https://docs\.google\.com/document/d/[A-Za-z0-9_-]+)")
NOTION_PAGE_ID_RE = re.compile(r"([0-9a-f]{32})", re.IGNORECASE)
JINA_PROXY_PREFIX = "https://r.jina.ai/"
JINA_PROXY_HOSTS = {
    "notion.so",
    "www.notion.so",
    "notion.site",
    "www.notion.site",
    "docs.google.com",
}
MIN_PROXY_WORD_COUNT = 10


class MarkdownConversionError(RuntimeError):
    """Raised when a URL cannot be converted into Markdown."""


@dataclass
class MarkdownResult:
    source_url: str
    final_url: str
    title: str | None
    markdown: str
    word_count: int
    metadata: Dict[str, Any]

    def to_payload(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = payload.get("metadata") or {}
        return payload


async def convert_url_to_markdown(url: str) -> MarkdownResult:
    """
    Convert a URL into Markdown using url2markdown.
    Falls back to a manual httpx + BeautifulSoup pipeline when necessary.
    """
    normalized_url, metadata = _normalize_special_urls(url)
    metadata = dict(metadata)  # copy to keep base metadata untouched
    notion_result = await _try_notion_api(normalized_url, url, metadata)
    if notion_result:
        return notion_result
    result: MarkdownResult | None = None
    try:
        result = await asyncio.to_thread(
            _convert_with_url2markdown, normalized_url, url, metadata
        )
    except Exception as exc:  # noqa: BLE001 - log and fall back
        logger.warning(
            "url2markdown fallback for %s due to %s", url, exc, exc_info=True
        )
    if result and not _needs_proxy_render(result, normalized_url):
        return result

    html, final_url = await _download_html(normalized_url)
    http_result = _markdown_from_html(
        html=html,
        original_url=url,
        final_url=final_url,
        metadata=metadata,
    )
    if not _needs_proxy_render(http_result, normalized_url):
        return http_result

    proxy_html = await _fetch_via_jina_proxy(normalized_url)
    if proxy_html:
        metadata = {**metadata, "renderer": "r.jina.ai"}
        return _markdown_from_html(
            html=proxy_html,
            original_url=url,
            final_url=normalized_url,
            metadata=metadata,
        )
    return http_result


def _convert_with_url2markdown(
    normalized_url: str, original_url: str, metadata: Dict[str, Any]
) -> MarkdownResult:
    article = url2markdown_downloader(normalized_url)
    html = getattr(article, "article_html", None) or getattr(article, "html", None)
    if not html:
        raise MarkdownConversionError("url2markdown returned empty HTML.")
    cleaned_html = _clean_html(html)
    markdown = _render_markdown(cleaned_html)
    if not markdown:
        raise MarkdownConversionError("Rendered Markdown is empty.")
    meta = dict(metadata)
    if getattr(article, "authors", None):
        meta["authors"] = article.authors
    if getattr(article, "publish_date", None):
        meta["publish_date"] = article.publish_date.isoformat()
    if getattr(article, "keywords", None):
        meta["keywords"] = article.keywords
    title = getattr(article, "title", None) or _extract_title_from_html(html)
    final_url = getattr(article, "url", None) or normalized_url
    return MarkdownResult(
        source_url=original_url,
        final_url=final_url,
        title=title,
        markdown=markdown,
        word_count=_word_count(markdown),
        metadata=meta,
    )


def _markdown_from_html(
    html: str, original_url: str, final_url: str, metadata: Dict[str, Any]
) -> MarkdownResult:
    if not html:
        raise MarkdownConversionError("Empty HTML response.")
    cleaned_html = _clean_html(html)
    markdown = _render_markdown(cleaned_html)
    if not markdown:
        raise MarkdownConversionError("Rendered Markdown is empty.")
    title = _extract_title_from_html(html)
    return MarkdownResult(
        source_url=original_url,
        final_url=final_url,
        title=title,
        markdown=markdown,
        word_count=_word_count(markdown),
        metadata=metadata,
    )


async def _download_html(url: str) -> Tuple[str, str]:
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, follow_redirects=True, timeout=30
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text, str(response.url)
    except httpx.HTTPError as exc:  # noqa: BLE001
        raise MarkdownConversionError(
            f"Failed to download HTML: {exc}"
        ) from exc


def _clean_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "lxml")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in soup.find_all(list(UNWANTED_TAGS)):
        tag.decompose()
    for selector in UNWANTED_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    main_node = _pick_main_node(soup)
    return str(main_node)


def _pick_main_node(soup: BeautifulSoup) -> BeautifulSoup:
    for selector in MAIN_CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node
    if soup.body and soup.body.get_text(strip=True):
        return soup.body
    return soup


def _render_markdown(clean_html: str) -> str:
    markdown = markdownify_html(clean_html, heading_style="ATX")
    cleaned_lines = [line.rstrip() for line in markdown.splitlines()]
    while cleaned_lines and not cleaned_lines[0].strip():
        cleaned_lines.pop(0)
    markdown = "\n".join(cleaned_lines).strip()
    return markdown


def _extract_title_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    heading = soup.find(["h1", "h2", "h3"])
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    return None


def _word_count(markdown: str) -> int:
    if not markdown:
        return 0
    tokens = [token for token in re.split(r"\s+", markdown) if token]
    return len(tokens)


def _normalize_special_urls(url: str) -> Tuple[str, Dict[str, Any]]:
    metadata: Dict[str, Any] = {}
    docs_match = GOOGLE_DOCS_RE.search(url)
    if docs_match:
        normalized = f"{docs_match.group(1)}/export?format=html"
        metadata["normalizer"] = "google-docs-html-export"
        return normalized, metadata
    parsed = urlparse(url)
    if "notion.so" in parsed.netloc and "pvs=" not in parsed.query:
        new_query_items = parse_qsl(parsed.query, keep_blank_values=True)
        new_query_items.append(("pvs", "4"))
        normalized = urlunparse(parsed._replace(query=urlencode(new_query_items)))
        metadata["normalizer"] = "notion-reader-mode"
        return normalized, metadata
    return url, metadata


async def _try_notion_api(
    normalized_url: str, original_url: str, metadata: Dict[str, Any]
) -> MarkdownResult | None:
    if "notion.so" not in urlparse(normalized_url).netloc:
        return None

    page_id = _extract_notion_page_id(normalized_url)
    if not page_id:
        return None

    api_url = f"https://notion-api.splitbee.io/v1/page/{page_id.replace('-', '')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            record_map = response.json()
    except httpx.HTTPError as exc:  # noqa: BLE001
        logger.warning("Notion API fetch failed for %s: %s", normalized_url, exc)
        return None
    except ValueError:
        logger.warning("Notion API returned invalid JSON for %s", normalized_url)
        return None

    markdown = _render_notion_page(record_map)
    if not markdown:
        return None

    title = _guess_notion_title(record_map)
    meta = {**metadata, "renderer": "notion-api"}
    return MarkdownResult(
        source_url=original_url,
        final_url=normalized_url,
        title=title,
        markdown=markdown,
        word_count=_word_count(markdown),
        metadata=meta,
    )


def _extract_notion_page_id(url: str) -> str | None:
    match = NOTION_PAGE_ID_RE.search(url.replace("-", ""))
    if not match:
        return None
    raw = match.group(1)
    # Return canonical hyphenated UUID.
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _render_notion_page(record_map: Dict[str, Any]) -> str:
    blocks = {
        block_id: entry.get("value")
        for block_id, entry in record_map.items()
        if isinstance(entry, dict) and entry.get("value")
    }
    page_block = next(
        (block for block in blocks.values() if block.get("type") == "page"), None
    )
    if not page_block:
        return ""

    title = _rich_text_to_markdown(
        page_block.get("properties", {}).get("title", [])
    )
    lines: List[str] = []
    if title:
        lines.append(f"# {title}")
        lines.append("")

    lines.extend(_render_notion_blocks(page_block.get("content", []), blocks, depth=0))
    markdown = "\n".join(line for line in lines if line is not None)
    return markdown.strip()


def _render_notion_blocks(
    block_ids: List[str], blocks: Dict[str, Any], depth: int
) -> List[str]:
    lines: List[str] = []
    for block_id in block_ids or []:
        block = blocks.get(block_id)
        if not block or not block.get("alive"):
            continue
        block_type = block.get("type")
        props = block.get("properties", {})
        text = _rich_text_to_markdown(props.get("title"))
        indent = "  " * depth

        if block_type in {"text", "paragraph"}:
            if text:
                lines.append(text)
                lines.append("")
        elif block_type == "header":
            lines.append(f"# {text}")
            lines.append("")
        elif block_type == "sub_header":
            lines.append(f"## {text}")
            lines.append("")
        elif block_type == "sub_sub_header":
            lines.append(f"### {text}")
            lines.append("")
        elif block_type == "bulleted_list":
            lines.append(f"{indent}- {text}")
        elif block_type == "numbered_list":
            lines.append(f"{indent}1. {text}")
        elif block_type == "to_do":
            checked = props.get("checked", [["No"]])[0][0] == "Yes"
            prefix = "x" if checked else " "
            lines.append(f"{indent}- [{prefix}] {text}")
        elif block_type == "quote":
            lines.append(f"> {text}")
            lines.append("")
        elif block_type == "code":
            language = props.get("language", [[""]])[0][0]
            lines.append(f"```{language}")
            lines.append(text)
            lines.append("```")
            lines.append("")
        elif block_type == "callout":
            icon = props.get("icon", [["💡"]])[0][0]
            lines.append(f"> {icon} {text}")
            lines.append("")
        elif block_type == "divider":
            lines.append("---")
            lines.append("")
        elif block_type == "image":
            source = props.get("source", [[""]])[0][0]
            if source:
                lines.append(f"![image]({source})")
                lines.append("")
        elif block_type == "toggle":
            lines.append(f"{indent}- {text}")
        else:
            if text:
                lines.append(text)
                lines.append("")

        children = block.get("content")
        if children:
            lines.extend(_render_notion_blocks(children, blocks, depth + 1))
    return lines


def _rich_text_to_markdown(rich_text: Any) -> str:
    if not rich_text:
        return ""
    parts: List[str] = []
    for fragment in rich_text:
        if not fragment:
            continue
        text = fragment[0]
        if len(fragment) > 1:
            for style in fragment[1:]:
                if not style:
                    continue
                if style[0] == "a" and len(style) > 1:
                    href = style[1]
                    text = f"[{text}]({href})"
        parts.append(text)
    return "".join(parts)


def _guess_notion_title(record_map: Dict[str, Any]) -> str | None:
    blocks = (
        entry.get("value")
        for entry in record_map.values()
        if isinstance(entry, dict) and entry.get("value")
    )
    for block in blocks:
        if block.get("type") == "page":
            text = _rich_text_to_markdown(
                block.get("properties", {}).get("title", [])
            )
            if text:
                return text
    return None


def _needs_proxy_render(result: MarkdownResult, url: str) -> bool:
    return (
        result.word_count < MIN_PROXY_WORD_COUNT
        and _should_use_jina_proxy(urlparse(url).netloc.lower())
    )


def _should_use_jina_proxy(host: str) -> bool:
    return any(
        host == allowed or host.endswith(f".{allowed}") for allowed in JINA_PROXY_HOSTS
    )


async def _fetch_via_jina_proxy(url: str) -> str | None:
    proxy_url = f"{JINA_PROXY_PREFIX}{url}"
    try:
        async with httpx.AsyncClient(
            headers=DEFAULT_HEADERS, follow_redirects=True, timeout=45
        ) as client:
            response = await client.get(proxy_url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:  # noqa: BLE001
        logger.warning("Jina proxy fetch failed for %s: %s", url, exc, exc_info=True)
        return None
