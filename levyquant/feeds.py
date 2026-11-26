"""Bounded, dependency-free RSS/Atom collection; never fetch article bodies."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


MAX_FEED_BYTES = 2 * 1024 * 1024
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_TRACKING_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "_hsenc", "_hsmi", "vero_id",
}


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.hidden += 1
        if not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _child(element: ET.Element, *names: str) -> ET.Element | None:
    for name in names:
        for candidate in element:
            if _local_name(candidate) == name:
                return candidate
    return None


def _markup(element: ET.Element | None) -> str:
    if element is None:
        return ""
    # Preserve nested XHTML boundaries before converting the summary to text.
    return (element.text or "") + "".join(
        ET.tostring(child, encoding="unicode") for child in element
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a timezone-aware datetime is required")
    return value.astimezone(timezone.utc)


def _date(value: str) -> datetime | None:
    value = value.strip()
    # Neither a calendar date nor an unzoned time identifies a publication instant.
    if not value or not re.search(r"\d{1,2}:\d{2}", value):
        return None
    offset = re.search(r"[+-](\d{2}):?(\d{2})$", value)
    if offset and (int(offset.group(1)) > 23 or int(offset.group(2)) > 59):
        return None
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
        r"(?:[Zz]|[+-]\d{2}:?\d{2})", value
    ):
        try:
            return _utc(datetime.fromisoformat(value[:-1] + "+00:00" if value[-1] in "Zz" else value))
        except (ValueError, OverflowError):
            return None
    if not re.fullmatch(
        r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+)?\d{1,2}\s+"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+"
        r"\d{1,2}:\d{2}(?::\d{2})?\s+"
        r"(?:[+-]\d{4}|UT|UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)", value, re.I
    ):
        return None
    try:
        return _utc(parsedate_to_datetime(value))
    except (ValueError, TypeError, OverflowError):
        return None


def _element_date(element: ET.Element, *names: str) -> datetime | None:
    for name in names:
        for candidate in element:
            if _local_name(candidate) == name:
                parsed = _date("".join(candidate.itertext()))
                if parsed is not None:
                    return parsed
    return None


def _clean_url(value: str, base: str = "") -> str:
    if not value.strip():
        return ""
    try:
        parts = urlsplit(urljoin(base, value.strip()))
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return ""
        if parts.username is not None or parts.password is not None:
            return ""
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        scheme = parts.scheme.lower()
        if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
            host += f":{port}"
        query = [
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
        ]
        # Stable key ordering preserves the order of repeated values of one key.
        query.sort(key=lambda pair: pair[0])
        return urlunsplit((scheme, host, parts.path or "/", urlencode(query), ""))
    except (ValueError, UnicodeError):
        return ""


def _entry_url(entry: ET.Element, base: str, atom: bool) -> str:
    if atom:
        links = [
            element for element in entry
            if _local_name(element) == "link"
            and element.get("rel", "alternate").lower() == "alternate"
            and element.get("href")
        ]
        links.sort(key=lambda element: element.get("type", "text/html") != "text/html")
        for link in links:
            link_base = urljoin(base, link.get(_XML_BASE, ""))
            url = _clean_url(link.get("href", ""), link_base)
            if url:
                return url
        return ""
    for link in entry:
        if _local_name(link) == "link":
            url = _clean_url("".join(link.itertext()), base)
            if url:
                return url
    guid = _child(entry, "guid")
    if guid is not None and guid.get("isPermaLink", "true").lower() != "false":
        return _clean_url("".join(guid.itertext()), base)
    return ""


def parse_feed(data: bytes | str, source: dict) -> list[dict]:
    """Parse RSS 2, Atom, or RSS 1/RDF, raising ParseError for malformed XML.

    Undated, unzoned, date-only, and invalid-calendar entries retain
    ``published_at=None``. Channel dates and collection time never substitute
    for an item's publication date. An explicit item update is a valid fallback.
    """
    root = ET.fromstring(data)
    kind = _local_name(root)
    atom = kind == "feed"
    container = _child(root, "channel") if kind == "rss" else root
    if container is None or kind not in {"rss", "rdf", "feed"}:
        return []
    base = urljoin(str(source.get("url") or ""), root.get(_XML_BASE, ""))
    if container is not root:
        base = urljoin(base, container.get(_XML_BASE, ""))
    label = str(source.get("name") or source.get("id") or "Unnamed source")
    source_id = str(source.get("id") or sha256(
        _clean_url(str(source.get("url") or "")).encode("utf-8")
    ).hexdigest()[:16])
    articles: list[dict] = []
    for entry in container:
        if _local_name(entry) != ("entry" if atom else "item"):
            continue
        entry_base = urljoin(base, entry.get(_XML_BASE, ""))
        url = _entry_url(entry, entry_base, atom)
        title = _plain_text(_markup(_child(entry, "title")))
        if not url or not title:
            continue
        published = _element_date(entry, "published", "pubdate", "date")
        date_basis = "published" if published is not None else None
        updated = _element_date(entry, "updated")
        if published is None and updated is not None:
            published, date_basis = updated, "updated"
        summary = _plain_text(_markup(_child(entry, "summary", "description", "encoded", "content")))
        article = {
            "id": sha256(url.encode("utf-8")).hexdigest(),
            "source": label,
            "source_id": source_id,
            "feed_url": str(source.get("url") or ""),
            "title": title,
            "url": url,
            "canonical_url": url,
            "summary": summary,
            "published_at": published.isoformat() if published is not None else None,
            "section": str(source.get("section") or "company"),
            "date_basis": date_basis,
            "content_scope": "rss_metadata_and_feed_excerpt",
        }
        if updated is not None:
            article["updated_at"] = updated.isoformat()
        articles.append(article)
    return articles


def _fetch_source(source: dict, timeout: int) -> list[dict]:
    source_url = _clean_url(str(source.get("url") or ""))
    if not source_url:
        raise ValueError("missing or invalid HTTP(S) feed URL")
    request = Request(source_url, headers={
        "User-Agent": "LevyQuantNews/1.0 (personal RSS digest)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9",
    })
    deadline = time.monotonic() + timeout
    with urlopen(request, timeout=timeout) as response:
        resolved_url = response.geturl() if hasattr(response, "geturl") else source_url
        if not _clean_url(resolved_url):
            raise ValueError("feed redirected to an unsupported URL")
        length = response.headers.get("Content-Length")
        if length and length.isdecimal() and int(length) > MAX_FEED_BYTES:
            raise ValueError(f"feed exceeds {MAX_FEED_BYTES} byte limit")
        chunks: list[bytes] = []
        size = 0
        read = getattr(response, "read1", response.read)
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("feed download exceeded time budget")
            chunk = read(min(64 * 1024, MAX_FEED_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise ValueError(f"feed exceeds {MAX_FEED_BYTES} byte limit")
            chunks.append(chunk)
    return parse_feed(b"".join(chunks), {**source, "url": resolved_url})


def collect_sources(
    sources: list[dict], *, since: datetime, until: datetime,
    timeout: int = 20, max_per_source: int = 30,
) -> tuple[list[dict], list[str]]:
    """Collect dated entries within the inclusive UTC window, preserving failures.

    At most four source downloads run concurrently. ``timeout`` bounds socket
    operations and is also checked between download chunks. Article bodies
    are never requested. Unknown dates are excluded with a source warning.
    """
    since, until = _utc(since), _utc(until)
    if since > until:
        raise ValueError("since must not be after until")
    if timeout <= 0 or max_per_source <= 0:
        raise ValueError("timeout and max_per_source must be positive")
    upper_bound = min(until, datetime.now(timezone.utc))
    enabled = [(index, source) for index, source in enumerate(sources) if source.get("enabled", True)]
    if not enabled:
        return [], ["No enabled news sources configured."]
    results: dict[int, tuple[list[dict], str | None]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(enabled))) as pool:
        futures = {pool.submit(_fetch_source, source, timeout): index for index, source in enabled}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = (future.result(), None)
            except Exception as error:
                results[index] = ([], f"{type(error).__name__}: {error}")
    articles: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for index, source in enabled:
        label = str(source.get("name") or source.get("id") or f"Source {index + 1}")
        entries, error = results[index]
        if error:
            warnings.append(f"{label}: {error}")
            continue
        if not entries:
            warnings.append(f"{label}: feed has no usable entries.")
            continue
        source_limit = source.get("max_items_per_run", max_per_source)
        if isinstance(source_limit, bool) or not isinstance(source_limit, int) or source_limit < 0:
            warnings.append(f"{label}: invalid max_items_per_run; source entries were excluded.")
            continue
        source_limit = min(max_per_source, source_limit)
        eligible: list[dict] = []
        unknown = future_dated = 0
        for article in entries:
            published = _date(article.get("published_at") or "")
            if published is None:
                unknown += 1
            elif published > upper_bound:
                future_dated += 1
            elif published >= since:
                eligible.append(article)
        if unknown:
            warnings.append(f"{label}: excluded {unknown} entries with unknown publication dates.")
        if future_dated:
            warnings.append(f"{label}: excluded {future_dated} entries dated after the cutoff or in the future.")
        eligible.sort(key=lambda article: (article["published_at"], article["id"]), reverse=True)
        source_seen: set[str] = set()
        kept = 0
        for article in eligible:
            if article["id"] in source_seen:
                continue
            source_seen.add(article["id"])
            if kept >= source_limit:
                break
            kept += 1
            if article["id"] not in seen:
                seen.add(article["id"])
                articles.append(article)
    articles.sort(key=lambda article: (article["published_at"], article["id"]), reverse=True)
    return articles, warnings
