from __future__ import annotations

import html
import json
import sys
import time
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from functools import reduce
from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


SERVER_NAME = "sakura-web-search"
SERVER_VERSION = "0.1.0"
DEFAULT_TIMEOUT_SECONDS = 12
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)

# AnySearch 统一实时搜索（首选源，匿名访问无需 API key）。
# 质量优于 Bing/DuckDuckGo 的裸 HTML 抓取；失败时自动降级到本地抓取源。
ANYSEARCH_ENDPOINT = "https://api.anysearch.com/mcp"
ANYSEARCH_TIMEOUT_SECONDS = 20

# 站内专用搜索：通用搜索引擎索引不到站内动态/结构化内容，用官方公开 API 直接查。
GITHUB_API_ENDPOINT = "https://api.github.com"
GITHUB_TIMEOUT_SECONDS = 15
BILIBILI_TIMEOUT_SECONDS = 15
# WBI 签名的 mixin key 重排表（B站 web 端固定常量）。
_BILI_MIXIN_KEY_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
# 进程内缓存 B站 cookie 与 WBI mixin key，避免每次搜索重复握手。
_BILI_STATE: dict[str, Any] = {"cookie": "", "mixin_key": "", "ts": 0.0}
_BILI_STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": "搜索公开网页，并返回标题、链接和简短摘要。适合查询最新信息、资料来源和网页入口。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条结果，范围 1-10。",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch_url",
        "description": "读取一个公开 http/https 网页，抽取标题、正文文本和页面链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的公开网页 URL，仅支持 http 或 https。",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "正文最多返回多少字符，范围 500-20000。",
                    "minimum": 500,
                    "maximum": 20000,
                    "default": 6000,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "github_search",
        "description": (
            "在 GitHub 上搜索仓库、代码、issue/PR 或用户。适合查开源项目、"
            "库、示例代码和技术讨论。通用搜索引擎搜不全 GitHub 站内内容时用这个。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，支持 GitHub 搜索语法（如 'live2d language:python stars:>100'）。",
                },
                "kind": {
                    "type": "string",
                    "description": "搜索类型：repositories(仓库) / code(代码) / issues(issue和PR) / users(用户)。",
                    "enum": ["repositories", "code", "issues", "users"],
                    "default": "repositories",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条结果，范围 1-10。",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bilibili_search",
        "description": (
            "在哔哩哔哩（B站）搜索视频或UP主。适合查B站上的视频内容、投稿和创作者。"
            "通用搜索引擎索引不到B站站内结果时用这个。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词。",
                },
                "search_type": {
                    "type": "string",
                    "description": "搜索类型：video(视频) / bili_user(UP主)。",
                    "enum": ["video", "bili_user"],
                    "default": "video",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条结果，范围 1-10。",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
    {
        "name": "bilibili_user_videos",
        "description": (
            "获取某个B站UP主最近投稿的视频列表，带精确发布时间。"
            "适合查『某UP主最近/昨天发了什么视频』这类实时问题。"
            "需要先用 bilibili_search(search_type='bili_user') 拿到 UP 主的 mid。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mid": {
                    "type": "integer",
                    "description": "UP主的用户ID（mid），可通过 bilibili_search 搜索UP主得到。",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回多少条最近投稿，范围 1-10。",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["mid"],
            "additionalProperties": False,
        },
    },
]


def main() -> int:
    try:
        _run_fastmcp_server()
        return 0
    except ImportError:
        # 测试环境或未安装 mcp 时保留轻量 JSON-RPC fallback，正式运行应使用 FastMCP。
        pass

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
        except Exception as exc:  # MCP Server 不能因为单条坏消息退出。
            response = _error_response(None, -32603, f"内部错误：{exc}")
        if response is not None:
            _write_message(response)
    return 0


def _run_fastmcp_server() -> None:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(SERVER_NAME, log_level="ERROR")

    @mcp.tool(
        name="web_search",
        description="搜索公开网页，并返回标题、链接和简短摘要。适合查询最新信息、资料来源和网页入口。",
        structured_output=True,
    )
    def web_search_tool(query: str, max_results: int = 5) -> dict[str, Any]:
        """搜索公开网页。"""

        return search_web(
            query=query,
            max_results=_clamp_int(max_results, default=5, minimum=1, maximum=10),
        )

    @mcp.tool(
        name="fetch_url",
        description="读取一个公开 http/https 网页，抽取标题、正文文本和页面链接。",
        structured_output=True,
    )
    def fetch_url_tool(url: str, max_chars: int = 6000) -> dict[str, Any]:
        """读取公开网页正文。"""

        return fetch_url(
            url=url,
            max_chars=_clamp_int(max_chars, default=6000, minimum=500, maximum=20000),
        )

    @mcp.tool(
        name="github_search",
        description=(
            "在 GitHub 上搜索仓库、代码、issue/PR 或用户。适合查开源项目、"
            "库、示例代码和技术讨论。通用搜索引擎搜不全 GitHub 站内内容时用这个。"
        ),
        structured_output=True,
    )
    def github_search_tool(
        query: str, kind: str = "repositories", max_results: int = 5
    ) -> dict[str, Any]:
        """在 GitHub 上搜索仓库/代码/issue/用户。"""

        return github_search(
            query=query,
            kind=_enum_string(
                kind,
                default="repositories",
                allowed=("repositories", "code", "issues", "users"),
            ),
            max_results=_clamp_int(max_results, default=5, minimum=1, maximum=10),
        )

    @mcp.tool(
        name="bilibili_search",
        description=(
            "在哔哩哔哩（B站）搜索视频或UP主。适合查B站上的视频内容、投稿和创作者。"
            "通用搜索引擎索引不到B站站内结果时用这个。"
        ),
        structured_output=True,
    )
    def bilibili_search_tool(
        keyword: str, search_type: str = "video", max_results: int = 5
    ) -> dict[str, Any]:
        """在B站搜索视频或UP主。"""

        return bilibili_search(
            keyword=keyword,
            search_type=_enum_string(
                search_type,
                default="video",
                allowed=("video", "bili_user"),
            ),
            max_results=_clamp_int(max_results, default=5, minimum=1, maximum=10),
        )

    @mcp.tool(
        name="bilibili_user_videos",
        description=(
            "获取某个B站UP主最近投稿的视频列表，带精确发布时间。"
            "适合查『某UP主最近/昨天发了什么视频』这类实时问题。"
            "需要先用 bilibili_search(search_type='bili_user') 拿到 UP 主的 mid。"
        ),
        structured_output=True,
    )
    def bilibili_user_videos_tool(mid: int, max_results: int = 5) -> dict[str, Any]:
        """获取B站UP主最近投稿视频。"""

        return bilibili_user_videos(
            mid=mid,
            max_results=_clamp_int(max_results, default=5, minimum=1, maximum=10),
        )

    mcp.run("stdio")


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if request_id is None:
        return None
    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or "2024-11-05")
        return _result_response(
            request_id,
            {
                "protocolVersion": requested_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _result_response(request_id, {})
    if method == "tools/list":
        return _result_response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        return _handle_tool_call(request_id, params)
    if method == "resources/list":
        return _result_response(request_id, {"resources": []})
    if method == "prompts/list":
        return _result_response(request_id, {"prompts": []})
    return _error_response(request_id, -32601, f"不支持的方法：{method}")


def _handle_tool_call(request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        if name == "web_search":
            payload = search_web(
                query=_required_string(arguments, "query"),
                max_results=_clamp_int(arguments.get("max_results"), default=5, minimum=1, maximum=10),
            )
        elif name == "fetch_url":
            payload = fetch_url(
                url=_required_string(arguments, "url"),
                max_chars=_clamp_int(arguments.get("max_chars"), default=6000, minimum=500, maximum=20000),
            )
        elif name == "github_search":
            payload = github_search(
                query=_required_string(arguments, "query"),
                kind=_enum_string(
                    arguments.get("kind"),
                    default="repositories",
                    allowed=("repositories", "code", "issues", "users"),
                ),
                max_results=_clamp_int(arguments.get("max_results"), default=5, minimum=1, maximum=10),
            )
        elif name == "bilibili_search":
            payload = bilibili_search(
                keyword=_required_string(arguments, "keyword"),
                search_type=_enum_string(
                    arguments.get("search_type"),
                    default="video",
                    allowed=("video", "bili_user"),
                ),
                max_results=_clamp_int(arguments.get("max_results"), default=5, minimum=1, maximum=10),
            )
        elif name == "bilibili_user_videos":
            payload = bilibili_user_videos(
                mid=_required_int(arguments, "mid"),
                max_results=_clamp_int(arguments.get("max_results"), default=5, minimum=1, maximum=10),
            )
        else:
            return _error_response(request_id, -32602, f"未知工具：{name}")
    except Exception as exc:
        return _result_response(
            request_id,
            {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        )
    return _tool_result_response(request_id, payload)


def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空。")

    # 首选 AnySearch 统一实时搜索（质量最好，匿名可用）；不可达时降级到
    # DuckDuckGo Lite / Bing 的裸 HTML 抓取，保证离线/被墙时仍有兜底。
    errors: list[str] = []
    for source_name, searcher in (
        ("AnySearch", _search_anysearch),
        ("DuckDuckGo", _search_duckduckgo),
        ("Bing", _search_bing),
    ):
        try:
            results = searcher(query)
        except Exception as exc:  # 单一搜索源失败时降级到下一个。
            errors.append(f"{source_name}: {exc}")
            continue
        deduped = _dedupe_results(results)[:max_results]
        if deduped:
            return {
                "query": query,
                "source": source_name,
                "results": [
                    {"title": item.title, "url": item.url, "snippet": item.snippet}
                    for item in deduped
                ],
            }
        errors.append(f"{source_name}: 未解析到结果")

    detail = "；".join(errors) if errors else "未知原因"
    raise RuntimeError(
        f"联网搜索暂时不可用（已尝试 AnySearch、DuckDuckGo 与 Bing）：{detail}"
    )


def _search_anysearch(query: str) -> list[SearchResult]:
    """通过 AnySearch MCP（Streamable HTTP）做统一实时搜索。

    匿名访问无需 API key；服务器返回 Markdown 文本块，形如：
        ### N. 标题
        - **URL**: https://...
        - 摘要文本
    解析这些块为结构化 SearchResult。
    """
    text = _anysearch_call("search", {"query": query})
    return _parse_anysearch_markdown(text)


def _anysearch_call(tool_name: str, arguments: dict[str, Any]) -> str:
    """调用 AnySearch MCP 工具，返回首个 text 内容块。

    AnySearch 原生 Streamable HTTP，匿名调用无需 initialize/session。
    响应体可能是纯 JSON 或 SSE（event:/data:）格式，两者都要处理。
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    request = Request(
        ANYSEARCH_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=ANYSEARCH_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        raise RuntimeError(f"AnySearch HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"AnySearch 网络请求失败：{exc.reason}") from exc

    parsed = _parse_mcp_response_body(raw)
    result = parsed.get("result")
    if not isinstance(result, dict):
        error = parsed.get("error")
        raise RuntimeError(f"AnySearch 返回异常：{error or parsed}")
    if result.get("isError"):
        detail = _extract_mcp_text(result)
        raise RuntimeError(f"AnySearch 工具报错：{detail[:200]}")
    return _extract_mcp_text(result)


def _parse_mcp_response_body(raw: str) -> dict[str, Any]:
    """解析 MCP 响应体：纯 JSON 或 SSE（event:/data:）两种格式。"""
    stripped = raw.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    for line in stripped.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    continue
    raise RuntimeError("无法解析 AnySearch 响应体")


def _extract_mcp_text(result: dict[str, Any]) -> str:
    """从 MCP result.content 中拼接所有 text 块。"""
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _parse_anysearch_markdown(text: str) -> list[SearchResult]:
    """解析 AnySearch 的 Markdown 结果块为 SearchResult 列表。

    结果块格式：
        ### 1. 标题
        - **URL**: https://...
        - 摘要行（可选，可能多行）
    """
    results: list[SearchResult] = []
    title = ""
    url = ""
    snippet_parts: list[str] = []

    def flush() -> None:
        if title and url and _looks_like_result_url(url):
            snippet = _normalize_space(" ".join(snippet_parts))
            results.append(SearchResult(title=title, url=url, snippet=snippet[:300]))

    for line in text.splitlines():
        stripped = line.strip()
        heading = _match_anysearch_heading(stripped)
        if heading is not None:
            flush()
            title = heading
            url = ""
            snippet_parts = []
            continue
        if not title:
            continue
        url_value = _match_anysearch_url(stripped)
        if url_value is not None:
            url = url_value
            continue
        if stripped.startswith("- "):
            snippet_parts.append(stripped[2:].strip())
        elif stripped:
            snippet_parts.append(stripped)
    flush()
    return results


def _match_anysearch_heading(line: str) -> str | None:
    """匹配 '### N. 标题' 结果标题行，返回标题文本。"""
    if not line.startswith("###"):
        return None
    body = line.lstrip("#").strip()
    # 去掉前导序号 'N. '
    dot = body.find(". ")
    if dot != -1 and body[:dot].strip().isdigit():
        return body[dot + 2 :].strip()
    return body or None


def _match_anysearch_url(line: str) -> str | None:
    """匹配 '- **URL**: https://...' 行，返回 URL。"""
    marker = "**URL**:"
    idx = line.find(marker)
    if idx == -1:
        return None
    return line[idx + len(marker) :].strip()


def _search_duckduckgo(query: str) -> list[SearchResult]:
    url = "https://lite.duckduckgo.com/lite/?" + urlencode({"q": query})
    html_text = _read_url_text(url, max_bytes=512_000)
    parser = DuckDuckGoLiteParser()
    parser.feed(html_text)
    return parser.results


def _search_bing(query: str) -> list[SearchResult]:
    url = "https://www.bing.com/search?" + urlencode({"q": query})
    html_text = _read_url_text(url, max_bytes=512_000)
    parser = BingSearchParser()
    parser.feed(html_text)
    return parser.results


def fetch_url(url: str, max_chars: int = 6000) -> dict[str, Any]:
    normalized_url = _validate_public_http_url(url)
    raw_text, content_type, final_url = _read_url_text_with_metadata(
        normalized_url,
        max_bytes=max(256_000, min(max_chars * 8, 1_500_000)),
    )
    if "html" in content_type.lower():
        parser = PageTextParser()
        parser.feed(raw_text)
        text = _normalize_space(parser.text)
        title = _normalize_space(parser.title)
        links = parser.links[:30]
    else:
        text = _normalize_space(raw_text)
        title = ""
        links = []
    return {
        "url": final_url,
        "content_type": content_type,
        "title": title,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "links": links,
    }


def github_search(query: str, kind: str = "repositories", max_results: int = 5) -> dict[str, Any]:
    """通过 GitHub 公开 Search API 搜索仓库/代码/issue/用户。

    匿名访问无需 token（速率限制约 10 req/min），返回结构化结果。
    """
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空。")

    endpoint = f"{GITHUB_API_ENDPOINT}/search/{kind}"
    url = endpoint + "?" + urlencode({"q": query, "per_page": max_results})
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"GitHub HTTP {exc.code}：{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub 网络请求失败：{exc.reason}") from exc

    data = json.loads(raw)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("GitHub 返回结果格式异常。")

    results = [_format_github_item(item, kind) for item in items[:max_results]]
    return {
        "query": query,
        "kind": kind,
        "total_count": data.get("total_count", len(results)),
        "results": results,
    }


def _format_github_item(item: dict[str, Any], kind: str) -> dict[str, Any]:
    """把 GitHub Search API 的单条结果规整成精简结构。"""
    if not isinstance(item, dict):
        return {"title": "", "url": "", "snippet": ""}
    if kind == "repositories":
        return {
            "title": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "snippet": _normalize_space(str(item.get("description") or ""))[:300],
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language") or "",
        }
    if kind == "code":
        repo = item.get("repository") if isinstance(item.get("repository"), dict) else {}
        return {
            "title": item.get("name", ""),
            "url": item.get("html_url", ""),
            "snippet": f"路径 {item.get('path', '')}",
            "repository": repo.get("full_name", ""),
        }
    if kind == "issues":
        return {
            "title": item.get("title", ""),
            "url": item.get("html_url", ""),
            "snippet": _normalize_space(str(item.get("body") or ""))[:300],
            "state": item.get("state", ""),
            "comments": item.get("comments", 0),
        }
    if kind == "users":
        return {
            "title": item.get("login", ""),
            "url": item.get("html_url", ""),
            "snippet": item.get("type", ""),
        }
    return {
        "title": str(item.get("name") or item.get("title") or ""),
        "url": item.get("html_url", ""),
        "snippet": "",
    }


def bilibili_search(keyword: str, search_type: str = "video", max_results: int = 5) -> dict[str, Any]:
    """通过 B站公开搜索 API 搜索视频或 UP 主。

    B站 web 搜索需要先握手拿到 buvid cookie 才能绕过 -412 风控；
    结果里的 HTML 高亮标签会被清理成纯文本。
    """
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword 不能为空。")

    cookie = _bili_ensure_cookie()
    url = "https://api.bilibili.com/x/web-interface/search/type?" + urlencode(
        {"search_type": search_type, "keyword": keyword, "page": 1}
    )
    data = _bili_api_get(url, cookie)
    result = data.get("data", {}).get("result")
    if not isinstance(result, list):
        return {"keyword": keyword, "search_type": search_type, "results": []}

    results: list[dict[str, Any]] = []
    for item in result[:max_results]:
        if not isinstance(item, dict):
            continue
        if search_type == "video":
            bvid = item.get("bvid", "")
            results.append(
                {
                    "title": _strip_html_tags(str(item.get("title") or "")),
                    "url": f"https://www.bilibili.com/video/{bvid}" if bvid else item.get("arcurl", ""),
                    "bvid": bvid,
                    "author": item.get("author", ""),
                    "play": item.get("play", 0),
                    "pubdate": _format_bili_ts(item.get("pubdate")),
                    "snippet": _strip_html_tags(str(item.get("description") or ""))[:200],
                }
            )
        else:  # bili_user
            mid = item.get("mid", 0)
            results.append(
                {
                    "title": item.get("uname", ""),
                    "url": f"https://space.bilibili.com/{mid}" if mid else "",
                    "mid": mid,
                    "fans": item.get("fans", 0),
                    "videos": item.get("videos", 0),
                    "snippet": _strip_html_tags(str(item.get("usign") or ""))[:200],
                }
            )
    return {"keyword": keyword, "search_type": search_type, "results": results}


def bilibili_user_videos(mid: int, max_results: int = 5) -> dict[str, Any]:
    """获取某 UP 主最近投稿的视频列表，带精确发布时间。

    主路径走 WBI 签名接口 x/space/wbi/arc/search（能拿到该 UP 主完整投稿列表）。
    该接口有较强的匿名风控（可能返回 -352/-799/412）；命中风控时自动降级到
    search/type 多页扫描，按 mid 精确过滤出该 UP 主的投稿并按发布时间排序。
    降级路径覆盖率不如主路径，但保证不报错、有数据、来源可辨。
    """
    try:
        return _bili_user_videos_arc(mid, max_results)
    except Exception as arc_error:  # arc/search 命中风控，降级到搜索扫描。
        fallback = _bili_user_videos_via_search(mid, max_results)
        fallback["note"] = (
            "UP主投稿接口被B站风控限流，已降级为搜索匹配，可能不是最新/最全投稿。"
            f"（arc/search: {arc_error}）"
        )
        return fallback


def _bili_user_videos_arc(mid: int, max_results: int) -> dict[str, Any]:
    """主路径：WBI 签名的 x/space/wbi/arc/search，返回 UP 主完整投稿列表。"""
    cookie = _bili_ensure_cookie()
    mixin_key = _bili_ensure_mixin_key(cookie)
    params = {
        "mid": mid,
        "ps": max_results,
        "pn": 1,
        "order": "pubdate",
        "platform": "web",
        # web_location 是 arc/search 风控必需参数；缺失会触发 -352/412。
        "web_location": 1550101,
    }
    signed = _bili_wbi_sign(params, mixin_key)
    url = "https://api.bilibili.com/x/space/wbi/arc/search?" + signed
    # arc/search 要求 Referer 指向该 UP 主空间页，否则 412 Precondition Failed。
    data = _bili_api_get(url, cookie, referer=f"https://space.bilibili.com/{mid}/video")
    vlist = data.get("data", {}).get("list", {}).get("vlist")
    if not isinstance(vlist, list):
        raise RuntimeError("arc/search 未返回投稿列表。")

    results: list[dict[str, Any]] = []
    for item in vlist[:max_results]:
        if not isinstance(item, dict):
            continue
        bvid = item.get("bvid", "")
        results.append(
            {
                "title": _strip_html_tags(str(item.get("title") or "")),
                "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                "bvid": bvid,
                "created": _format_bili_ts(item.get("created")),
                "length": item.get("length", ""),
                "play": item.get("play", 0),
                "snippet": _strip_html_tags(str(item.get("description") or ""))[:200],
            }
        )
    return {"mid": mid, "source": "arc_search", "results": results}


def _bili_user_videos_via_search(mid: int, max_results: int) -> dict[str, Any]:
    """降级路径：先用 card 接口拿 UP 主名，再 search/type 多页扫描按 mid 过滤。

    search/type 是独立风控桶，稳定可用；缺点是只能捞到搜索结果里该 UP 主的投稿，
    覆盖率不如 arc/search。命中的结果按 pubdate 降序，取前 max_results 条。
    """
    cookie = _bili_ensure_cookie()
    uname = _bili_user_name(mid, cookie)
    if not uname:
        return {"mid": mid, "source": "search_fallback", "results": []}

    seen: set[str] = set()
    own: list[dict[str, Any]] = []
    for page in (1, 2, 3):
        url = "https://api.bilibili.com/x/web-interface/search/type?" + urlencode(
            {"search_type": "video", "keyword": uname, "page": page}
        )
        try:
            data = _bili_api_get(url, cookie)
        except Exception:
            break
        result = data.get("data", {}).get("result")
        if not isinstance(result, list):
            break
        for item in result:
            if not isinstance(item, dict):
                continue
            if item.get("mid") != mid:
                continue
            bvid = item.get("bvid", "")
            if bvid and bvid in seen:
                continue
            if bvid:
                seen.add(bvid)
            own.append(item)
        time.sleep(0.3)

    own.sort(key=lambda v: v.get("pubdate", 0) if isinstance(v.get("pubdate"), (int, float)) else 0, reverse=True)
    results: list[dict[str, Any]] = []
    for item in own[:max_results]:
        bvid = item.get("bvid", "")
        results.append(
            {
                "title": _strip_html_tags(str(item.get("title") or "")),
                "url": f"https://www.bilibili.com/video/{bvid}" if bvid else item.get("arcurl", ""),
                "bvid": bvid,
                "created": _format_bili_ts(item.get("pubdate")),
                "length": item.get("duration", ""),
                "play": item.get("play", 0),
                "snippet": _strip_html_tags(str(item.get("description") or ""))[:200],
            }
        )
    return {"mid": mid, "source": "search_fallback", "uname": uname, "results": results}


def _bili_user_name(mid: int, cookie: str) -> str:
    """通过 card 接口拿到 UP 主昵称，供降级搜索使用。"""
    url = "https://api.bilibili.com/x/web-interface/card?" + urlencode({"mid": mid})
    try:
        data = _bili_api_get(url, cookie)
    except Exception:
        return ""
    card = data.get("data", {}).get("card", {})
    return str(card.get("name") or "") if isinstance(card, dict) else ""


def _bili_ensure_cookie() -> str:
    """获取并缓存 B站访问所需的 buvid cookie（带 TTL）。"""
    now = time.time()
    if _BILI_STATE["cookie"] and now - _BILI_STATE["ts"] < _BILI_STATE_TTL_SECONDS:
        return _BILI_STATE["cookie"]
    request = Request(
        "https://www.bilibili.com/",
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=BILIBILI_TIMEOUT_SECONDS) as response:
            set_cookies = response.headers.get_all("Set-Cookie") or []
    except HTTPError as exc:
        raise RuntimeError(f"B站握手 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"B站握手失败：{exc.reason}") from exc

    parts: list[str] = []
    for raw in set_cookies:
        name_value = raw.split(";", 1)[0].strip()
        if name_value.startswith(("buvid3=", "buvid4=", "b_nut=", "b_lsid=")):
            parts.append(name_value)
    cookie = "; ".join(parts)
    if not cookie:
        # 兜底：至少给一个 buvid3，B站接口对匿名请求要求宽松。
        cookie = "buvid3=" + hashlib.md5(str(now).encode()).hexdigest().upper() + "infoc"
    _BILI_STATE["cookie"] = cookie
    _BILI_STATE["ts"] = now
    return cookie


def _bili_ensure_mixin_key(cookie: str) -> str:
    """获取并缓存 WBI 签名所需的 mixin_key（img_key + sub_key 重排）。"""
    now = time.time()
    if _BILI_STATE["mixin_key"] and now - _BILI_STATE["ts"] < _BILI_STATE_TTL_SECONDS:
        return _BILI_STATE["mixin_key"]
    url = "https://api.bilibili.com/x/web-interface/nav"
    data = _bili_api_get(url, cookie, allow_not_login=True)
    wbi = data.get("data", {}).get("wbi_img", {})
    img_url = str(wbi.get("img_url") or "")
    sub_url = str(wbi.get("sub_url") or "")
    img_key = img_url.rsplit("/", 1)[-1].split(".", 1)[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".", 1)[0]
    if not img_key or not sub_key:
        raise RuntimeError("B站 WBI 密钥获取失败。")
    raw_key = img_key + sub_key
    mixin_key = reduce(lambda acc, i: acc + raw_key[i], _BILI_MIXIN_KEY_TABLE, "")[:32]
    _BILI_STATE["mixin_key"] = mixin_key
    return mixin_key


def _bili_wbi_sign(params: dict[str, Any], mixin_key: str) -> str:
    """对参数做 WBI 签名，返回带 wts/w_rid 的 urlencoded 查询串。"""
    params = dict(params)
    params["wts"] = int(time.time())
    ordered = {key: params[key] for key in sorted(params)}
    # WBI 要求值里过滤掉 !'()* 字符。
    filtered = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in ordered.items()
    }
    query = urlencode(filtered, quote_via=quote)
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return query + "&w_rid=" + w_rid


def _bili_api_get(
    url: str,
    cookie: str,
    allow_not_login: bool = False,
    referer: str = "https://www.bilibili.com/",
) -> dict[str, Any]:
    """调用 B站 JSON API，校验 code 字段。

    referer 对部分风控接口（如 arc/search）必须指向对应页面，默认用站点首页。
    """
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Cookie": cookie,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=BILIBILI_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        raise RuntimeError(f"B站 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"B站网络请求失败：{exc.reason}") from exc

    data = json.loads(raw)
    code = data.get("code")
    # nav 接口未登录时返回 code=-101，但 wbi_img 仍然有效，允许放行。
    if code not in (0, None) and not (allow_not_login and code == -101):
        raise RuntimeError(f"B站接口返回错误 code={code}：{data.get('message', '')}")
    return data


def _strip_html_tags(text: str) -> str:
    """清理 B站搜索结果里的 <em class=...> 高亮标签等 HTML。"""
    if not text:
        return ""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            if depth:
                depth -= 1
        elif depth == 0:
            out.append(ch)
    return _normalize_space(html.unescape("".join(out)))


def _format_bili_ts(value: Any) -> str:
    """把 B站的 Unix 秒时间戳格式化成可读时间。"""
    if not isinstance(value, (int, float)) or value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return ""


class DuckDuckGoLiteParser(HTMLParser):
    """解析 DuckDuckGo Lite 结果页的标题、真实链接和摘要。

    Lite 页面把每条结果渲染为 <a class="result-link"> 标题链接，紧随其后的
    <td class="result-snippet"> 为摘要；链接是 //duckduckgo.com/l/?uddg=<编码真实URL>
    形式的跳转，需要解码还原目标地址。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._in_result_link = False
        self._active_href = ""
        self._active_text: list[str] = []
        self._in_snippet = False
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        classes = set(attrs_map.get("class", "").split())
        if tag == "a" and "result-link" in classes:
            href = _decode_duckduckgo_redirect(attrs_map.get("href", ""))
            if href:
                self._active_href = href
                self._active_text = []
                self._in_result_link = True
        elif "result-snippet" in classes:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._active_text.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            title = _normalize_space("".join(self._active_text))
            if title and _looks_like_result_url(self._active_href):
                self.results.append(SearchResult(title=title, url=self._active_href))
            self._active_href = ""
            self._active_text = []
            self._in_result_link = False
        elif tag == "td" and self._in_snippet:
            snippet = _normalize_space("".join(self._snippet_parts))
            if snippet and self.results:
                previous = self.results[-1]
                if not previous.snippet:
                    self.results[-1] = SearchResult(
                        title=previous.title,
                        url=previous.url,
                        snippet=snippet[:300],
                    )
            self._in_snippet = False
            self._snippet_parts = []


class BingSearchParser(HTMLParser):
    """解析 Bing 搜索结果页中自然搜索结果的标题、链接和摘要。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._result_depth = 0
        self._heading_depth = 0
        self._in_title_link = False
        self._in_snippet = False
        self._active_href = ""
        self._active_text: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        classes = set(attrs_map.get("class", "").split())
        if tag == "li" and "b_algo" in classes:
            self._result_depth = 1
            self._snippet_parts = []
            return
        if self._result_depth:
            self._result_depth += 1
        if self._result_depth and tag == "h2":
            self._heading_depth = 1
            return
        if self._heading_depth:
            self._heading_depth += 1
        if self._heading_depth and tag == "a":
            href = _normalize_result_href(attrs_map.get("href", ""))
            if href:
                self._active_href = href
                self._active_text = []
                self._in_title_link = True
        elif self._result_depth and tag == "p":
            self._in_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title_link and self._active_href:
            self._active_text.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title_link:
            title = _normalize_space("".join(self._active_text))
            if title and _looks_like_result_url(self._active_href):
                self.results.append(SearchResult(title=title, url=self._active_href))
            self._active_href = ""
            self._active_text = []
            self._in_title_link = False
        elif tag == "p" and self._in_snippet:
            snippet = _normalize_space("".join(self._snippet_parts))
            if snippet and self.results:
                previous = self.results[-1]
                if not previous.snippet and snippet != previous.title:
                    self.results[-1] = SearchResult(
                        title=previous.title,
                        url=previous.url,
                        snippet=snippet[:300],
                    )
            self._in_snippet = False
            self._snippet_parts = []
        if self._heading_depth:
            self._heading_depth -= 1
        if self._result_depth:
            self._result_depth -= 1

class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[dict[str, str]] = []
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._active_link: str | None = None
        self._active_link_text: list[str] = []

    @property
    def text(self) -> str:
        return "\n".join(self._text_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = attrs_map.get("href", "")
            if href.startswith(("http://", "https://")):
                self._active_link = href
                self._active_link_text = []
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._active_link is not None:
            self._active_link_text.append(data)
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
            self.title = "".join(self._title_parts)
        elif tag == "a" and self._active_link is not None:
            text = _normalize_space("".join(self._active_link_text))
            if text:
                self.links.append({"text": text[:120], "url": self._active_link})
            self._active_link = None
            self._active_link_text = []


def _read_url_text(url: str, max_bytes: int) -> str:
    text, _content_type, _final_url = _read_url_text_with_metadata(url, max_bytes)
    return text


def _read_url_text_with_metadata(url: str, max_bytes: int) -> tuple[str, str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/plain"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(max_bytes + 1)
            final_url = response.geturl()
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"网络请求失败：{exc.reason}") from exc

    charset = _charset_from_content_type(content_type)
    if len(body) > max_bytes:
        body = body[:max_bytes]
    try:
        return body.decode(charset, errors="replace"), content_type, final_url
    except LookupError:
        return body.decode("utf-8", errors="replace"), content_type, final_url


def _charset_from_content_type(content_type: str) -> str:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip()
    return "utf-8"


def _normalize_result_href(href: str) -> str:
    href = html.unescape(href.strip())
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://www.bing.com" + href
    parsed = urlparse(href)
    if _is_bing_host(parsed.netloc) and parsed.path.startswith("/ck/"):
        target = _decode_bing_redirect_target(parsed)
        if target:
            href = target
    return href


def _looks_like_result_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    return not (_is_bing_host(host) or _is_duckduckgo_host(host))


def _decode_duckduckgo_redirect(href: str) -> str:
    href = html.unescape(href.strip())
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if _is_duckduckgo_host(parsed.netloc) and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target.startswith(("http://", "https://")):
            return target
        return unquote(target)
    return href


def _is_bing_host(host: str) -> bool:
    normalized = host.lower()
    return normalized == "bing.com" or normalized.endswith(".bing.com")


def _is_duckduckgo_host(host: str) -> bool:
    normalized = host.lower()
    return normalized == "duckduckgo.com" or normalized.endswith(".duckduckgo.com")


def _decode_bing_redirect_target(parsed_url: Any) -> str:
    raw_target = parse_qs(parsed_url.query).get("u", [""])[0]
    if not raw_target:
        return ""
    raw_target = unquote(raw_target)
    if raw_target.startswith(("http://", "https://")):
        return raw_target
    encoded = raw_target[2:] if raw_target.startswith("a1") else raw_target
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    return decoded if decoded.startswith(("http://", "https://")) else ""


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for item in results:
        key = item.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _validate_public_http_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url 必须是完整的 http 或 https 地址。")
    host = parsed.hostname or ""
    if _is_blocked_host(host):
        raise ValueError("出于安全考虑，不允许读取本机或私有网络地址。")
    return url


def _is_blocked_host(host: str) -> bool:
    normalized = host.strip("[]").lower()
    if normalized in {"localhost"} or normalized.endswith(".localhost"):
        return True
    try:
        address = ip_address(normalized)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} 必须是非空字符串。")
    return value


def _required_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} 必须是整数。")
    return value


def _enum_string(value: Any, default: str, allowed: tuple[str, ...]) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"取值必须是 {', '.join(allowed)} 之一。")
    return value


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("数值参数必须是整数。")
    if value < minimum or value > maximum:
        raise ValueError(f"数值参数必须在 {minimum}-{maximum} 之间。")
    return value


def _normalize_space(value: str) -> str:
    lines = [" ".join(line.split()) for line in html.unescape(value).splitlines()]
    return "\n".join(line for line in lines if line)


def _tool_result_response(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return _result_response(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "structuredContent": payload,
            "isError": False,
        },
    )


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
