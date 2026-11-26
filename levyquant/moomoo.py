"""Bounded public Moomoo headline search; never fetch article or image URLs.

Only the fixed public search endpoint is contacted. Results carry titles, links
and source publication instants, not article bodies or independent verification.
The shared collector applies the time window and final cross-source ID dedupe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPException
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .feeds import _clean_url, _date, _date_metadata, _plain_text
from .render import _safe_url


ENDPOINT = "https://ai-news-search.moomoo.com/news_search"
USER_AGENT = "moomoo-news-search/0.0.2 (Skill)"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
_ERROR_CODES = frozenset({"invalid_configuration", "http_error", "redirect_rejected",
    "source_timeout", "source_bytes_exceeded", "invalid_response", "api_error", "network_error"})
_NUMERIC_DATE = re.compile(r"[+-]?\d+(?:\.\d+)?")


class MoomooSourceError(RuntimeError):
    """Only fixed codes and an optional integer HTTP status cross the boundary."""
    def __init__(self, code: str, *, http_status: int | None = None):
        self.code = code if isinstance(code, str) and code in _ERROR_CODES else "invalid_response"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _configuration(source: dict, timeout: float) -> tuple[list[str], int, str, int]:
    if not isinstance(source, dict):
        raise MoomooSourceError("invalid_configuration")
    queries, size = source.get("queries"), source.get("search_size", 5)
    language, cap = source.get("language", "en"), source.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES)
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 4
            or any(not isinstance(query, str) or not query.strip() or len(query) > 200
                   or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in query) for query in queries)
            or type(size) is not int or not 1 <= size <= 10
            or language not in ("en", "zh-CN", "zh-HK")
            or type(cap) is not int or not 1 <= cap <= DEFAULT_MAX_RESPONSE_BYTES
            or isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 180 or not math.isfinite(timeout)
            or source.get("url", ENDPOINT) != ENDPOINT):
        raise MoomooSourceError("invalid_configuration")
    for field in ("id", "name", "section"):
        value = source.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()
                                  or any(ord(char) < 32 for char in value)):
            raise MoomooSourceError("invalid_configuration")
    return [query.strip() for query in queries], size, language, cap


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MoomooSourceError("source_timeout")
    return remaining


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError


def _search(opener, url: str, deadline: float, remaining_bytes: int) -> tuple[list[dict], int]:
    if remaining_bytes <= 0:
        raise MoomooSourceError("source_bytes_exceeded")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                    "Accept-Encoding": "identity"})
    try:
        with opener.open(request, timeout=_remaining(deadline)) as response:
            if response.geturl() != url:
                raise MoomooSourceError("redirect_rejected")
            if response.status != 200:
                raise MoomooSourceError("http_error", http_status=response.status)
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in ("", "identity"):
                raise MoomooSourceError("invalid_response")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in ("application/json", "text/json"):
                raise MoomooSourceError("invalid_response")
            length = response.headers.get("Content-Length", "")
            if str(length).isdecimal() and int(length) > remaining_bytes:
                raise MoomooSourceError("source_bytes_exceeded")
            raw, size = [], 0
            reader = getattr(response, "read1", response.read)
            while True:
                remaining_time = _remaining(deadline)
                # urllib's HTTPResponse exposes this socket through its reader.
                # Refresh its timeout so later reads share the source deadline.
                socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if socket is not None:
                    socket.settimeout(remaining_time)
                chunk = reader(min(65536, remaining_bytes - size + 1))
                _remaining(deadline)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise MoomooSourceError("invalid_response")
                size += len(chunk)
                if size > remaining_bytes:
                    raise MoomooSourceError("source_bytes_exceeded")
                raw.append(chunk)
        _remaining(deadline)
        value = json.loads(b"".join(raw).decode("utf-8-sig"), object_pairs_hook=_pairs,
                           parse_constant=_invalid_constant)
    except MoomooSourceError:
        raise
    except HTTPError as error:
        status = error.code
        error.close()
        code = "redirect_rejected" if type(status) is int and 300 <= status <= 399 else "http_error"
        raise MoomooSourceError(code, http_status=status) from None
    except TimeoutError:
        raise MoomooSourceError("source_timeout") from None
    except URLError as error:
        code = "source_timeout" if isinstance(error.reason, TimeoutError) else "network_error"
        raise MoomooSourceError(code) from None
    except (OSError, HTTPException):
        raise MoomooSourceError("network_error") from None
    except (ValueError, TypeError, UnicodeError):
        raise MoomooSourceError("invalid_response") from None
    if not isinstance(value, dict) or type(value.get("code")) is not int:
        raise MoomooSourceError("invalid_response")
    if value["code"] != 0:
        raise MoomooSourceError("api_error")
    data = value.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise MoomooSourceError("invalid_response")
    return data, size


def _publication(value) -> tuple[str | None, dict]:
    raw = str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None
    if raw is not None and len(raw) > 128:
        raw = None
    metadata = {"date_raw": raw, "date_zone": None, "date_timezone_status": "unusable"}
    if raw is None:
        return None, metadata
    if _NUMERIC_DATE.fullmatch(raw) or isinstance(value, (int, float)):
        try:
            number = float(raw)
            if not math.isfinite(number):
                return None, metadata
            # Contemporary Unix millisecond epochs have at least twelve digits.
            seconds = number / 1000 if abs(number) >= 100_000_000_000 else number
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None, metadata
        metadata.update(date_zone="UTC", date_timezone_status="explicit_timezone")
        return moment.isoformat(), metadata
    # An ISO unknown offset must not be upgraded into a known publication instant.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt ].*-(?:00:00|0000)", raw):
        return None, metadata
    moment = _date(raw)
    metadata.update(_date_metadata(raw, usable=moment is not None))
    return moment.isoformat() if moment is not None else None, metadata


def _canonical_url(raw: str) -> str:
    clean = _clean_url(raw)
    parts = urlsplit(clean)
    # Verified Moomoo search links use these keys only for search attribution.
    # Keep similarly named parameters on external publishers and other routes.
    if parts.hostname == "www.moomoo.com" and parts.path.startswith(("/news/", "/community/")):
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if key.casefold() not in {"futusource", "src"}]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return clean


def fetch_moomoo_source(source: dict, timeout: float) -> list[dict]:
    """Search 1–4 configured public queries within one time/byte budget.

    ``queries`` is required; ``search_size`` defaults to 5 (1–10), ``language``
    to en, and ``max_response_bytes`` to 1 MiB (may only be reduced). No retry,
    authentication, article fetch or image fetch is performed. Different date
    variants of the same link survive until the shared collector filters dates.
    """
    queries, size, language, cap = _configuration(source, timeout)
    deadline = time.monotonic() + timeout
    opener, used = build_opener(_NoRedirect()), 0
    articles, seen = [], set()
    for query in queries:
        url = ENDPOINT + "?" + urlencode({"keyword": query, "size": size, "news_type": 1,
                                         "lang": language, "sort_type": 2})
        data, count = _search(opener, url, deadline, cap - used)
        used += count
        for item in data[:size]:
            raw_title, raw_url = item.get("title"), item.get("url")
            if not isinstance(raw_title, str) or not isinstance(raw_url, str) or not _safe_url(raw_url):
                continue
            title, canonical = _plain_text(raw_title).strip(), _canonical_url(raw_url)
            if not title or not canonical or not _safe_url(canonical):
                continue
            published, metadata = _publication(item.get("publish_time"))
            identifier = sha256(canonical.encode("utf-8")).hexdigest()
            identity = (identifier, published)
            if identity in seen:
                continue
            seen.add(identity)
            articles.append({"id": identifier, "source_id": source.get("id") or "moomoo",
                "source": source.get("name") or "Moomoo public headline search", "feed_url": ENDPOINT,
                "title": title, "url": canonical, "canonical_url": canonical,
                "summary": "", "body": "", "source_text": title, "published_at": published,
                "date_basis": "published" if published is not None else None,
                "section": source.get("section") or "company", "content_scope": "search_headline_and_link",
                "media_type": "headline_only", "retrieval": "feed_excerpt_only", "verified_numbers": [],
                **metadata})
    return articles
