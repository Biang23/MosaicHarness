from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, PrivateAttr

from ..builtins.base import MosaicTool
from ..tools.result import ToolResult


class FetchUrlArgs(BaseModel):
    url: str = Field(min_length=1, max_length=4_000)
    max_bytes: int = Field(default=2_000_000, ge=1_000, le=10_000_000)


class FetchUrlTool(MosaicTool):
    name: str = "fetch_url"
    description: str = "Fetch public web page text for source verification."
    category = "network"
    risk_level = "medium"
    required_categories = ("network",)
    _timeout_seconds: float = PrivateAttr()
    _allowed_domains: tuple[str, ...] = PrivateAttr()

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        allowed_domains: tuple[str, ...] = (),
    ) -> None:
        super().__init__(args_schema=FetchUrlArgs)
        self._timeout_seconds = timeout_seconds
        self._allowed_domains = tuple(domain.casefold() for domain in allowed_domains)

    def _run(self, url: str, max_bytes: int = 2_000_000, **kwargs: object) -> ToolResult:
        del kwargs
        return asyncio.run(self._fetch(url, max_bytes))

    async def _arun(self, url: str, max_bytes: int = 2_000_000, **kwargs: object) -> ToolResult:
        del kwargs
        return await self._fetch(url, max_bytes)

    async def _fetch(self, url: str, max_bytes: int) -> ToolResult:
        try:
            body, content_type, final_url = await asyncio.to_thread(
                _fetch_text,
                url,
                max_bytes,
                self._timeout_seconds,
                self._allowed_domains,
            )
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            return ToolResult.error(
                f"URL fetch failed: {type(exc).__name__}",
                next_actions=("verify_url_and_retry", "stop_if_private_or_blocked"),
            )
        return ToolResult.success(
            f"Fetched {final_url}",
            data={"url": final_url, "content_type": content_type, "text": body},
            artifacts=(final_url,),
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _fetch_text(
    url: str,
    max_bytes: int,
    timeout_seconds: float,
    allowed_domains: tuple[str, ...],
) -> tuple[str, str, str]:
    _validate_url(url, allowed_domains)
    opener = urllib.request.build_opener(_RedirectGuard(allowed_domains))
    request = urllib.request.Request(url, headers={"User-Agent": "MosaicHarness/0.2"})
    with opener.open(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        _validate_url(final_url, allowed_domains)
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "text/plain", "application/json", "application/xml"}:
            raise ValueError(f"unsupported content type: {content_type}")
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("response exceeds max_bytes")
        decoded = body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    if content_type == "text/html":
        parser = _TextExtractor()
        parser.feed(decoded)
        decoded = "\n".join(parser.parts)
    return decoded, content_type, final_url


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_domains: tuple[str, ...], max_redirects: int = 3) -> None:
        self.allowed_domains = allowed_domains
        self.max_redirects = max_redirects
        self.count = 0

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        self.count += 1
        if self.count > self.max_redirects:
            raise ValueError("too many redirects")
        _validate_url(newurl, self.allowed_domains)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str, allowed_domains: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only absolute http(s) URLs are allowed")
    hostname = parsed.hostname.casefold().rstrip(".")
    if allowed_domains and not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains
    ):
        raise ValueError("domain is not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("private or reserved network address is not allowed")
