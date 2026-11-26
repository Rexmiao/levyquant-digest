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
MIN_SOURCE_FEED_BYTES = 256 * 1024
MAX_SOURCE_FEED_BYTES = 8 * 1024 * 1024
DIAGNOSTIC_STATUSES = frozenset({
    "disabled", "failed", "invalid_configuration", "empty_feed",
    "unusable_dates", "no_new_items", "ok",
})
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_RFC_DATE = re.compile(
    r"(?:(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+)?\d{1,2}\s+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s+"
    r"\d{1,2}:\d{2}(?::\d{2})?\s+"
    r"(?P<zone>[+-]\d{4}|UT|UTC|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)", re.I,
)
_RFC_NEGATIVE_ZERO_DATE = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),[ \t]+)?\d{1,2}[ \t]+"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[ \t]+\d{4}[ \t]+"
    r"\d{2}:\d{2}(?::\d{2})?[ \t]+-0000", re.I,
)
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
    rfc = _RFC_DATE.fullmatch(value)
    if rfc is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if rfc.group("zone") == "-0000":
            # RFC 5322 section 3.3: -0000 specifies a UTC instant while
            # withholding the originating local zone. Python returns naive
            # here; this exception never applies to genuinely unzoned input.
            if _RFC_NEGATIVE_ZERO_DATE.fullmatch(value) is None or parsed.year < 1900:
                return None
            weekday = rfc.group("weekday")
            if weekday and weekday.casefold() != ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[parsed.weekday()]:
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        return _utc(parsed)
    except (ValueError, TypeError, OverflowError):
        return None


def _element_date(element: ET.Element, *names: str) -> datetime | None:
    return _element_date_source(element, *names)[0]


def _element_date_source(element: ET.Element, *names: str) -> tuple[datetime | None, str | None]:
    first_raw = None
    for name in names:
        for candidate in element:
            if _local_name(candidate) == name:
                raw = "".join(candidate.itertext()).strip()
                if first_raw is None:
                    first_raw = raw
                parsed = _date(raw)
                if parsed is not None:
                    return parsed, raw
    return None, first_raw


def _date_metadata(raw: str | None, *, usable: bool) -> dict:
    if raw is None:
        return {}
    rfc = _RFC_DATE.fullmatch(raw)
    offset = re.search(r"([Zz]|[+-]\d{2}:?\d{2})$", raw)
    zone = rfc.group("zone") if rfc else offset.group(1) if offset else None
    status = ("local_zone_unknown" if usable and rfc is not None and zone == "-0000"
              else "explicit_timezone" if usable else "unusable")
    return {"date_raw": raw, "date_zone": zone, "date_timezone_status": status}


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


def _audio_url(entry: ET.Element, base: str, atom: bool) -> str:
    for element in entry:
        name = _local_name(element)
        if name == "enclosure":
            candidate = element.get("url", "")
        elif atom and name == "link" and element.get("rel", "").lower() == "enclosure":
            candidate = element.get("href", "")
        else:
            continue
        media_type = element.get("type", "").strip().lower()
        url = _clean_url(candidate, urljoin(base, element.get(_XML_BASE, "")))
        if not url or (media_type and not media_type.startswith("audio/")):
            continue
        if media_type.startswith("audio/") or urlsplit(url).path.lower().endswith((
                ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")):
            return url
    return ""


def _entry_summary(entry: ET.Element) -> str:
    for name in ("summary", "description", "encoded", "content"):
        for element in entry:
            if _local_name(element) == name:
                text = _plain_text(_markup(element))
                if text:
                    return text
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
        # A well-formed HTML login/access page is not a successfully read empty
        # feed. Let collection report failure instead of claiming connectivity.
        raise ValueError("unsupported feed document or missing RSS channel")
    base = urljoin(str(source.get("url") or ""), root.get(_XML_BASE, ""))
    if container is not root:
        base = urljoin(base, container.get(_XML_BASE, ""))
    label = str(source.get("name") or source.get("id") or "Unnamed source")
    source_id = str(source.get("id") or sha256(
        _clean_url(str(source.get("url") or "")).encode("utf-8")
    ).hexdigest()[:16])
    podcast = source.get("kind") == "podcast"
    articles: list[dict] = []
    for entry in container:
        if _local_name(entry) != ("entry" if atom else "item"):
            continue
        entry_base = urljoin(base, entry.get(_XML_BASE, ""))
        url = _entry_url(entry, entry_base, atom)
        audio_url = _audio_url(entry, entry_base, atom) if podcast else ""
        if not url and podcast:
            url = audio_url
        title = _plain_text(_markup(_child(entry, "title")))
        if not url or not title:
            continue
        published, date_raw = _element_date_source(entry, "published", "pubdate", "date")
        date_basis = "published" if published is not None else None
        updated, updated_raw = _element_date_source(entry, "updated")
        if published is None and updated is not None:
            published, date_basis, date_raw = updated, "updated", updated_raw
        summary = _entry_summary(entry)
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
            "content_scope": "podcast_episode_description" if podcast else "rss_metadata_and_feed_excerpt",
        }
        article.update(_date_metadata(date_raw, usable=published is not None))
        if podcast:
            article.update(media_type="podcast", retrieval="feed_excerpt_only")
            if audio_url:
                article["audio_url"] = audio_url
        elif source.get("retrieval") is not None:
            article["retrieval"] = str(source["retrieval"])
        if updated is not None:
            article["updated_at"] = updated.isoformat()
        articles.append(article)
    return articles


def _feed_limit(source: dict) -> int:
    limit = source.get("max_feed_bytes", MAX_FEED_BYTES)
    if (type(limit) is not int or not MIN_SOURCE_FEED_BYTES <= limit <= MAX_SOURCE_FEED_BYTES):
        raise ValueError("invalid max_feed_bytes; expected an integer from 262144 to 8388608")
    return limit


def _fetch_source(source: dict, timeout: int) -> list[dict]:
    limit = _feed_limit(source)
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
        if length and length.isdecimal() and int(length) > limit:
            raise ValueError(f"feed exceeds {limit} byte limit")
        chunks: list[bytes] = []
        size = 0
        read = getattr(response, "read1", response.read)
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("feed download exceeded time budget")
            chunk = read(min(64 * 1024, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError(f"feed exceeds {limit} byte limit")
            chunks.append(chunk)
    return parse_feed(b"".join(chunks), {**source, "url": resolved_url})


def collect_sources(
    sources: list[dict], *, since: datetime, until: datetime,
    timeout: int = 20, max_per_source: int = 30,
    diagnostics: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    """Collect dated entries within the inclusive UTC window, preserving failures.

    At most four source downloads run concurrently. ``timeout`` bounds socket
    operations and is also checked between download chunks. Article bodies
    are never requested. Unknown dates are excluded with a source warning.
    If supplied, diagnostics receives one record per configured source in
    manifest order. A valid feed with no dates in the window is no_new_items,
    not failed; parsed counts usable metadata entries, not raw XML items.
    """
    since, until = _utc(since), _utc(until)
    if since > until:
        raise ValueError("since must not be after until")
    if timeout <= 0 or max_per_source <= 0:
        raise ValueError("timeout and max_per_source must be positive")
    upper_bound = min(until, datetime.now(timezone.utc))
    reports = [{"id": str(source.get("id") or f"source_{index + 1}"),
                "name": str(source.get("name") or source.get("id") or f"Source {index + 1}"),
                "enabled": bool(source.get("enabled", True)),
                "status": "failed" if source.get("enabled", True) else "disabled",
                "parsed": 0, "dated": 0, "eligible": 0, "selected": 0,
                "latest_published": None, "unknown_dates": 0, "future_dated": 0}
               for index, source in enumerate(sources)]
    enabled = [(index, source) for index, source in enumerate(sources) if source.get("enabled", True)]
    if not enabled:
        if diagnostics is not None:
            diagnostics.extend(reports)
        return [], ["No enabled news sources configured."]
    results: dict[int, tuple[list[dict], str | None]] = {}
    ready = []
    for index, source in enabled:
        try:
            _feed_limit(source)  # Reject unsafe per-source caps before any I/O.
            ready.append((index, source))
        except ValueError as error:
            reports[index]["status"] = "invalid_configuration"
            results[index] = ([], f"ValueError: {error}")
    if ready:
        with ThreadPoolExecutor(max_workers=min(4, len(ready))) as pool:
            futures = {pool.submit(_fetch_source, source, timeout): index for index, source in ready}
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
        report = reports[index]
        report["parsed"] = len(entries)
        if error:
            warnings.append(f"{label}: {error}")
            continue
        if not entries:
            report["status"] = "empty_feed"
            warnings.append(f"{label}: feed has no usable entries.")
            continue
        source_limit = source.get("max_items_per_run", max_per_source)
        if isinstance(source_limit, bool) or not isinstance(source_limit, int) or source_limit < 0:
            report["status"] = "invalid_configuration"
            warnings.append(f"{label}: invalid max_items_per_run; source entries were excluded.")
            continue
        source_limit = min(max_per_source, source_limit)
        eligible: list[dict] = []
        unknown = future_dated = 0
        dated = []
        for article in entries:
            published = _date(article.get("published_at") or "")
            if published is None:
                unknown += 1
            else:
                dated.append(published)
                if published > upper_bound:
                    future_dated += 1
                elif published >= since:
                    eligible.append(article)
        report.update(dated=len(dated), eligible=len(eligible), unknown_dates=unknown,
                      future_dated=future_dated,
                      latest_published=max(dated).isoformat() if dated else None,
                      status="unusable_dates" if not dated else "ok" if eligible else "no_new_items")
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
                report["selected"] += 1
    articles.sort(key=lambda article: (article["published_at"], article["id"]), reverse=True)
    if diagnostics is not None:
        diagnostics.extend(reports)
    return articles, warnings
