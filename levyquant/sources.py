"""Extract public official-source text without credentials, paywall workarounds or PDFs.

RSS summaries remain intact. ``source_text`` is the best available material for
an editor, while ``content_scope`` says whether it is an excerpt, abstract, or
text extracted from an official page. No extraction is claimed to be complete.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import re
from threading import Lock
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .feeds import _clean_url


MAX_PAGE_BYTES = 2 * 1024 * 1024
ALLOWED_HOSTS = frozenset({
    "www.federalreserve.gov", "arxiv.org", "rss.arxiv.org", "www.sec.gov",
    "www.apple.com", "nvidianews.nvidia.com", "ir.nasdaq.com", "www.bls.gov",
})
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_HIDDEN_TAGS = frozenset({
    "head", "script", "style", "noscript", "svg", "nav", "header", "footer",
    "aside", "form", "button", "select", "template", "canvas", "iframe",
    "object", "video", "audio",
})
_BLOCK_TAGS = frozenset({"article", "main", "section", "div", "p", "br", "hr", "li", "blockquote", "h1", "h2", "h3", "h4", "tr"})
_NOISE = re.compile(r"(?:^|[-_\s])(cookie|consent|breadcrumb|navigation|navbar|sidebar|social|share|related|advertisement|advertising|newsletter)(?:$|[-_\s])", re.I)
_BODY_MARKER = re.compile(r"article[-_]?body|pagebody[-_]?copy|field--name-body|bodytext|release[-_]?(?:body|content)|news[-_]?(?:body|content)|story[-_]?(?:body|content)", re.I)
_ACCESS_NOTICE = re.compile(r"access denied|verify (?:that )?you are human|sign in to (?:continue|read)|subscribe to (?:continue|read)|enable javascript and cookies", re.I)


def _official_url(value: str) -> str:
    clean = _clean_url(value)
    if not clean:
        raise ValueError("missing or invalid public article URL")
    parts = urlsplit(clean)
    if parts.hostname not in ALLOWED_HOSTS or parts.port is not None:
        raise ValueError("article URL is outside the official-source allowlist")
    # Feed links occasionally use HTTP. Only fetch the same known host over HTTPS.
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))


class _OfficialRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Validate before urllib can contact a redirect target, not after fetching it.
        approved = _official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, approved)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.candidates: list[dict] = []
        self.active: list[dict] = []
        self.fallback: list[str] = []

    def _boundary(self) -> None:
        self.fallback.append("\n")
        for candidate in self.active:
            candidate["parts"].append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        marker = attributes.get("id", "") + " " + attributes.get("class", "")
        inherited_hidden = bool(self.stack and self.stack[-1][1])
        hidden = inherited_hidden or tag in _HIDDEN_TAGS or bool(_NOISE.search(marker))
        hidden = hidden or "hidden" in attributes or attributes.get("aria-hidden", "").lower() == "true"
        hidden = hidden or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attributes.get("style", ""), re.I))
        if not hidden and tag in _BLOCK_TAGS:
            self._boundary()
        if tag in _VOID_TAGS:
            return
        self.stack.append((tag, hidden))
        if hidden:
            return
        priority, scope = 0, "official_page_text"
        if attributes.get("itemprop", "").lower() == "articlebody" or _BODY_MARKER.search(marker):
            priority, scope = 120, "official_article_text"
        elif "abstract" in marker.lower().split() or tag == "blockquote" and "abstract" in marker.lower():
            priority, scope = 130, "official_abstract"
        elif tag == "article":
            priority, scope = 110, "official_article_text"
        elif tag == "main" or attributes.get("role", "").lower() == "main":
            priority = 90
        elif tag == "body":
            priority = 10
        if priority:
            candidate = {"depth": len(self.stack), "priority": priority, "scope": scope, "parts": []}
            self.candidates.append(candidate)
            self.active.append(candidate)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        match = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index][0] == tag), None)
        if match is None:
            return
        if not self.stack[-1][1] and tag in _BLOCK_TAGS:
            self._boundary()
        self.active = [candidate for candidate in self.active if candidate["depth"] <= match]
        del self.stack[match:]

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1][1]:
            return
        self.fallback.append(data)
        for candidate in self.active:
            candidate["parts"].append(data)


def _normal_text(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
    return "\n\n".join(line for line in lines if line)


def extract_html_text(html: str) -> tuple[str, str]:
    """Return visible text and its scope, preferring article/abstract containers.

    Does not execute scripts, fetch linked resources, infer dates, or claim to
    have read a paper when only its abstract page is available.
    """
    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    candidates = [(candidate, _normal_text(candidate["parts"])) for candidate in parser.candidates]
    # Avoid selecting an empty teaser container above a usable main section.
    usable = [(candidate, text) for candidate, text in candidates if len(text) >= 160]
    if usable:
        candidate, text = max(usable, key=lambda entry: (entry[0]["priority"], len(entry[1])))
        return text, candidate["scope"]
    return _normal_text(parser.fallback), "official_page_text"


def _fetch_page(url: str, timeout: int) -> tuple[str, str, str]:
    approved = _official_url(url)
    request = Request(approved, headers={
        "User-Agent": "LevyQuantNews/1.0 (public official-source text reader)",
        "Accept": "text/html, application/xhtml+xml, text/plain;q=0.8",
        "Accept-Encoding": "identity",
    })
    deadline = time.monotonic() + timeout
    with build_opener(_OfficialRedirectHandler()).open(request, timeout=timeout) as response:
        final_url = _official_url(response.geturl())
        content_type = response.headers.get("Content-Type", "").lower()
        media_type = content_type.split(";", 1)[0].strip()
        if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise ValueError("unsupported article content type; retained RSS excerpt")
        if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
            raise ValueError("unsupported compressed response; retained RSS excerpt")
        length = str(response.headers.get("Content-Length", ""))
        if length.isdecimal() and int(length) > MAX_PAGE_BYTES:
            raise ValueError(f"official page exceeds {MAX_PAGE_BYTES} byte limit")
        chunks: list[bytes] = []
        size = 0
        read = getattr(response, "read1", response.read)
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("official page exceeded download time budget")
            chunk = read(min(65536, MAX_PAGE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise ValueError(f"official page exceeds {MAX_PAGE_BYTES} byte limit")
            chunks.append(chunk)
        charset = re.search(r"charset\s*=\s*[\"']?([^\s;\"']+)", content_type)
        encoding = charset.group(1) if charset else "utf-8"
        try:
            document = b"".join(chunks).decode(encoding, errors="replace")
        except LookupError:
            document = b"".join(chunks).decode("utf-8", errors="replace")
    if _ACCESS_NOTICE.search(document[:12000]):
        raise ValueError("access restriction or verification page; retained RSS excerpt")
    if media_type == "text/plain":
        text, scope = _normal_text([document]), "official_page_text"
    else:
        text, scope = extract_html_text(document)
    if len(text) < 160:
        raise ValueError("official page has insufficient readable text; retained RSS excerpt")
    return text, scope, final_url


def enrich_articles(
    articles: list[dict], *, timeout: int = 20, max_workers: int = 4,
    min_summary_chars: int = 500, max_articles: int = 30,
) -> tuple[list[dict], list[str]]:
    """Fetch official text for short excerpts, returning copied articles/warnings.

    Identity, dates and original ``summary`` remain unchanged. ``source_text``
    is accompanied by ``content_scope`` and ``enrichment_status``. Unsupported
    hosts, SEC filings, PDFs, blocked pages and request failures retain the RSS
    excerpt. At most four requests run concurrently, one per initial host;
    HTTP 401/403/429 blocks later requests to that host for this collection.
    """
    if timeout <= 0 or max_workers <= 0 or min_summary_chars < 0 or max_articles < 0:
        raise ValueError("invalid enrichment limits")
    output = []
    for article in articles:
        excerpt = str(article.get("summary") or "")
        output.append({**article, "body": "", "source_text": excerpt,
                       "content_scope": "rss_metadata_and_feed_excerpt", "enrichment_status": "retained_excerpt"})
    warnings_by_index: dict[int, str] = {}
    jobs: list[tuple[int, str]] = []
    for index, article in enumerate(output):
        if len(article["source_text"]) >= min_summary_chars:
            article["enrichment_status"] = "excerpt_sufficient"
            continue
        try:
            url = _official_url(str(article.get("url") or ""))
        except ValueError as error:
            warnings_by_index[index] = f"{article.get('source', 'Source')}: {error}"
            continue
        parts = urlsplit(url)
        if parts.hostname == "www.sec.gov":
            article["enrichment_status"] = "sec_excerpt_only"
            warnings_by_index[index] = "SEC: filing-body extraction is not implemented; retained RSS excerpt."
            continue
        if parts.path.lower().endswith(".pdf") or parts.hostname == "arxiv.org" and parts.path.startswith("/pdf/"):
            article["enrichment_status"] = "pdf_excerpt_only"
            warnings_by_index[index] = f"{article.get('source', 'Source')}: PDF extraction is not implemented; retained RSS excerpt."
            continue
        if len(jobs) >= max_articles:
            article["enrichment_status"] = "budget_excerpt_only"
            continue
        jobs.append((index, url))
    if not jobs:
        return output, [warnings_by_index[index] for index in sorted(warnings_by_index)]
    locks = {urlsplit(url).hostname: Lock() for _, url in jobs}
    blocked_hosts: set[str] = set()

    def fetch(index: int, url: str):
        host = urlsplit(url).hostname
        with locks[host]:
            if host in blocked_hosts:
                return index, None, "Host previously restricted access or rate-limited this collection; no retry was attempted."
            try:
                return index, _fetch_page(url, timeout), None
            except HTTPError as error:
                if error.code in {401, 403, 429}:
                    blocked_hosts.add(host)
                return index, None, f"HTTP {error.code}; retained RSS excerpt."
            except Exception as error:
                return index, None, f"{type(error).__name__}: {error}"

    with ThreadPoolExecutor(max_workers=min(4, max_workers, len(jobs))) as pool:
        futures = [pool.submit(fetch, index, url) for index, url in jobs]
        for future in as_completed(futures):
            index, result, error = future.result()
            article = output[index]
            if error:
                article["enrichment_status"] = "failed_excerpt_retained"
                warnings_by_index[index] = f"{article.get('source', 'Source')}: {error}"
                continue
            text, scope, final_url = result
            if len(text) <= len(article["source_text"]):
                article["enrichment_status"] = "excerpt_sufficient"
                continue
            article.update(body=text, source_text=text, content_scope=scope,
                           body_url=final_url, enrichment_status="official_text_extracted")
    return output, [warnings_by_index[index] for index in sorted(warnings_by_index)]
