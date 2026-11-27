"""Render a full digest as Gmail-friendly HTML and a plain-text alternative.

Model output remains text. Only article records selected through ``source_ids``
can supply links; the renderer never turns model-supplied markup into HTML.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

RECIPIENT_FOOTER_SLOT = "<!--LEVYQUANT_RECIPIENT_FOOTER-->"

_LABELS = {
    "zh-CN": {
        "cutoff": "资料截止",
        "coverage": "资料覆盖提醒",
        "analysis": "编辑分析",
        "source": "来源",
        "missing_source": "来源链接缺失或待核实",
        "unavailable_link": "链接不可用",
        "source_count": "引用原文",
        "demo": "演示模板 / 非实时新闻 / 禁止发送",
        "unknown_mode": "运行模式未确认 / 禁止发送",
        "not_provided": "未提供",
        "empty": "本期没有可展示的内容。",
    },
    "en": {
        "cutoff": "Information cutoff",
        "coverage": "Coverage notice",
        "analysis": "Editorial analysis",
        "source": "Source",
        "missing_source": "Source link missing or unverified",
        "unavailable_link": "Link unavailable",
        "source_count": "Source articles",
        "demo": "DEMO TEMPLATE / NOT LIVE NEWS / DO NOT SEND",
        "unknown_mode": "MODE UNCONFIRMED / DO NOT SEND",
        "not_provided": "Not provided",
        "empty": "No items are available for this edition.",
    },
}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def format_new_york_time(value: object) -> str:
    """Display a known instant in New York; preserve dates without a known offset."""
    text = _text(value)
    if not text or text.endswith(("-00:00", "-0000")):
        return text
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        instant = datetime.fromisoformat(normalized)
        if instant.utcoffset() is None:
            return text
        local = instant.astimezone(ZoneInfo("America/New_York"))
    except (ValueError, OverflowError):
        return text
    return local.strftime("%Y-%m-%d %H:%M %Z")


def _html(value: object) -> str:
    return escape(_text(value), quote=True).replace("\n", "<br>")


def _safe_url(value: object) -> str:
    """Return an absolute HTTP(S) URL, or no URL for malformed input."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127
        or char in '\\<>"\''
        for char in candidate
    ):
        return ""
    try:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return ""
        # Accessing port validates malformed/non-numeric/out-of-range ports.
        parsed.port
    except ValueError:
        return ""
    return candidate


def _records(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _item_sources(item: dict, article_index: dict[str, dict]) -> list[tuple[str, dict]]:
    identifiers = item.get("source_ids", [])
    if not isinstance(identifiers, list):
        return []
    seen = set()
    selected = []
    for identifier in identifiers:
        if not isinstance(identifier, str) or identifier in seen:
            continue
        seen.add(identifier)
        if identifier in article_index:
            selected.append((identifier, article_index[identifier]))
    return selected


def _digest_language(digest: dict) -> str:
    return "zh-CN" if _text(digest.get("language", "zh-CN")).lower().startswith("zh") else "en"


def _document_start(title: str, language: str) -> str:
    return "".join([
        '<!doctype html>',
        f'<html lang="{language}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{escape(title, quote=True)}</title></head>',
        '<body style="margin:0;padding:0;background-color:#ffffff;color:#202124;',
        'font-family:Arial,Helvetica,sans-serif;">',
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" ',
        'style="width:100%;border-collapse:collapse;background-color:#ffffff;">',
        '<tr><td align="center" style="padding:22px 16px;">',
        '<table role="presentation" width="760" cellpadding="0" cellspacing="0" border="0" ',
        'style="width:100%;max-width:760px;border-collapse:collapse;text-align:left;">',
    ])


def _render_digest_body(digest: dict, articles: list[dict]) -> tuple[list[str], list[str], set[str]]:
    """Render trusted markup from escaped fields, excluding document and footer."""
    language = _digest_language(digest)
    labels = _LABELS[language]
    title = _text(digest.get("title")) or "LevyQuant Daily"
    edition = _text(digest.get("edition"))
    date = _text(digest.get("date"))
    cutoff = format_new_york_time(digest.get("cutoff")) or labels["not_provided"]
    subtitle = " · ".join(part for part in (edition, date) if part)
    mode = _text(digest.get("mode")).lower()
    banner = labels["demo"] if mode == "demo" else labels["unknown_mode"] if mode != "live" else ""

    article_index: dict[str, dict] = {}
    for article in _records(articles):
        identifier = article.get("id")
        if isinstance(identifier, str) and identifier and identifier not in article_index:
            article_index[identifier] = article

    html_parts = []
    text_parts = []
    if banner:
        html_parts.append(
            '<tr><td style="padding:12px 14px;background-color:#fce8e6;'
            'border:2px solid #b3261e;color:#8c1d18;font-size:15px;line-height:1.5;'
            f'font-weight:bold;">{_html(banner)}</td></tr>'
        )
        text_parts.extend([f"!!! {banner} !!!", ""])

    html_parts.append(
        '<tr><td style="padding:16px 0 18px;">'
        f'<h1 style="margin:0 0 8px;font-size:27px;line-height:1.25;font-weight:700;">{_html(title)}</h1>'
    )
    if subtitle:
        html_parts.append(f'<p style="margin:0 0 6px;font-size:15px;line-height:1.5;">{_html(subtitle)}</p>')
    html_parts.append(
        '<p style="margin:0;color:#5f6368;font-size:12px;line-height:1.5;">'
        f'{_html(labels["cutoff"])}: {_html(cutoff)}</p></td></tr>'
    )
    text_parts.append(title)
    if subtitle:
        text_parts.append(subtitle)
    text_parts.extend([f'{labels["cutoff"]}: {cutoff}', ""])

    linked_ids = set()
    item_count = 0
    for section in _records(digest.get("sections", [])):
        items = _records(section.get("items", []))
        if not items:
            continue
        section_title = _text(section.get("title")) or _text(section.get("id"))
        html_parts.append(
            '<tr><td style="padding:25px 0 8px;border-bottom:1px solid #dadce0;">'
            '<h2 style="margin:0;font-size:16px;line-height:1.4;font-weight:700;'
            f'letter-spacing:0.25px;">{_html(section_title)}</h2></td></tr>'
            '<tr><td style="padding:4px 0 0;">'
        )
        text_parts.extend([section_title, "-" * 36])
        for item in items:
            item_count += 1
            item_title = _text(item.get("title"))
            summary = _text(item.get("summary"))
            analysis = _text(item.get("analysis"))
            html_parts.append('<div style="margin:0;padding:11px 0;font-size:14px;line-height:1.6;">')
            if item_title:
                html_parts.append(f'<p style="margin:0 0 3px;font-weight:bold;">{_html(item_title)}</p>')
                text_parts.append(f"- {item_title}")
            if summary:
                html_parts.append(f'<p style="margin:0 0 4px;">{_html(summary)}</p>')
                text_parts.append(summary)
            if analysis:
                html_parts.append(
                    '<p style="margin:5px 0;color:#4b5563;">'
                    f'<strong>{_html(labels["analysis"])}:</strong> {_html(analysis)}</p>'
                )
                text_parts.append(f'{labels["analysis"]}: {analysis}')

            sources_html = []
            sources_text = []
            has_link = False
            for identifier, article in _item_sources(item, article_index):
                source_name = _text(article.get("source")) or _text(article.get("title")) or labels["source"]
                published_at = format_new_york_time(article.get("published_at"))
                safe_url = _safe_url(article.get("url"))
                timestamp = f" · {published_at}" if published_at else ""
                if safe_url:
                    linked_ids.add(identifier)
                    has_link = True
                    sources_html.append(
                        f'<a href="{escape(safe_url, quote=True)}" '
                        'target="_blank" rel="noopener noreferrer" '
                        f'style="color:#1a73e8;text-decoration:underline;">{_html(source_name)}</a>{_html(timestamp)}'
                    )
                    sources_text.append(f"{source_name}{timestamp} — {safe_url}")
                else:
                    sources_html.append(f'{_html(source_name)}{_html(timestamp)} ({_html(labels["unavailable_link"])})')
                    sources_text.append(f'{source_name}{timestamp} ({labels["unavailable_link"]})')
            if not has_link:
                sources_html.append(_html(labels["missing_source"]))
                sources_text.append(labels["missing_source"])
            html_parts.append(
                '<p style="margin:5px 0 0;color:#5f6368;font-size:12px;line-height:1.6;">'
                + '<br>'.join(sources_html) + '</p></div>'
            )
            text_parts.extend(f'{labels["source"]}: {source}' for source in sources_text)
            text_parts.append("")
        html_parts.append('</td></tr>')

    if not item_count:
        html_parts.append(f'<tr><td style="padding:20px 0;font-size:14px;">{_html(labels["empty"])}</td></tr>')
        text_parts.extend([labels["empty"], ""])
    warnings = digest.get("coverage_warnings", [])
    if not isinstance(warnings, list):
        warnings = [warnings] if warnings else []
    warnings = [_text(warning) for warning in warnings if _text(warning)]
    if warnings:
        html_parts.append(
            '<tr data-digest-block="coverage"><td style="padding:16px 0 12px;'
            'border-top:1px solid #e5e7eb;color:#6b7280;font-size:11px;line-height:1.55;">'
            f'<strong style="font-size:11px;font-weight:600;">{_html(labels["coverage"])}</strong>'
        )
        text_parts.append(labels["coverage"])
        for warning in warnings:
            html_parts.append(f'<div style="margin-top:4px;">{_html(warning)}</div>')
            text_parts.append(f"- {warning}")
        html_parts.append('</td></tr>')
        text_parts.append("")
    return html_parts, text_parts, linked_ids


def _render_document(body: str, text_parts: list[str], *, title: str, language: str,
                     linked_ids: set[str], personalize: bool) -> tuple[str, str]:
    labels = _LABELS[language]
    footer = f'LevyQuant · Macro, U.S. equities and quantitative research · {labels["source_count"]}: {len(linked_ids)}'
    recipient_slot = RECIPIENT_FOOTER_SLOT if personalize else ""
    footer_html = (
        '<tr data-digest-block="footer"><td style="padding:16px 0 0;border-top:1px solid #dadce0;'
        f'color:#70757a;font-size:12px;line-height:1.5;">{_html(footer)}{recipient_slot}</td></tr>'
        '</table></td></tr></table></body></html>'
    )
    return (_document_start(title, language) + body + footer_html,
            "\n".join([*text_parts, footer]).rstrip() + "\n")


def render_digest(digest: dict, articles: list[dict]) -> tuple[str, str]:
    """Return complete HTML and plain text without sending or writing files."""
    html_parts, text_parts, linked_ids = _render_digest_body(digest, articles)
    return _render_document("".join(html_parts), text_parts,
                            title=_text(digest.get("title")) or "LevyQuant Daily",
                            language=_digest_language(digest), linked_ids=linked_ids,
                            personalize=digest.get("footer_personalization") is True)


def _bilingual_structure(digest: dict) -> list:
    return [(section.get("id"), [item.get("source_ids", [])
             for item in _records(section.get("items", []))])
            for section in _records(digest.get("sections", []))]


def render_bilingual_digest(english: dict, chinese: dict, articles: list[dict]) -> tuple[str, str]:
    """Render full English then Chinese copies with one common recipient footer.

    Translation/provenance validation belongs upstream. This boundary additionally
    rejects mismatched edition metadata and ordered source-reference structures.
    """
    if (any(_text(english.get(key)) != _text(chinese.get(key)) for key in ("date", "cutoff", "mode"))
            or _bilingual_structure(english) != _bilingual_structure(chinese)):
        raise ValueError("Bilingual digests must share edition metadata and ordered source references.")
    bodies, text_parts, linked_ids = [], [], set()
    for digest, language, heading in ((english, "en", "English edition"),
                                      (chinese, "zh-CN", "简体中文版")):
        rows, lines, cited = _render_digest_body({**digest, "language": language}, articles)
        bodies.append(
            f'<tr><td lang="{language}" data-digest-language="{language}" style="padding:0;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="width:100%;border-collapse:collapse;text-align:left;">'
            '<tr><td style="padding:18px 0 0;color:#5f6368;font-size:13px;line-height:1.5;'
            f'font-weight:700;">{heading}</td></tr>'
            + "".join(rows) + '</table></td></tr>'
        )
        text_parts.extend([heading, "", *lines])
        linked_ids.update(cited)
    return _render_document("".join(bodies), text_parts,
                            title=_text(english.get("title")) or "LevyQuant Daily",
                            language="en", linked_ids=linked_ids,
                            personalize=any(digest.get("footer_personalization") is True
                                            for digest in (english, chinese)))
