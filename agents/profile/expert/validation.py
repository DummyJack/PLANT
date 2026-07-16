# Validates and normalizes agent output data formats.
import json
import re
from urllib.parse import unquote, urlparse
from typing import Any, Dict, List


research_fields = (
    "findings",
    "sources",
    "constraints",
    "risks",
    "recommendations",
)

trace_fields = (
    "findings",
    "constraints",
    "risks",
    "recommendations",
)

excluded_source_hosts = {
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "linkedin.com",
    "www.linkedin.com",
    "medium.com",
    "www.medium.com",
    "plurk.com",
    "www.plurk.com",
    "reddit.com",
    "www.reddit.com",
    "threads.net",
    "www.threads.net",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
    "line.naver.jp",
}
excluded_source_paths = {
    "/share.php",
    "/home/",
    "/r/msg/text/",
}
low_credibility_path_terms = (
    "/blog/",
    "/blogs/",
    "/article/",
    "/articles/",
    "/newsletter",
    "/newsletters",
    "/press-release",
    "/reel/",
    "/share",
)
trusted_host_keywords = (
    ".gov.",
    ".gov/",
    ".gov.tw/",
    "gov.tw/",
    ".edu.",
    ".edu/",
    ".ac.",
    ".ac/",
    "fsc.gov",
    "ftc.gov",
    "ncc.gov",
    "iso.org",
    "iec.ch",
    "nist.gov",
    "w3.org",
    "owasp.org",
    "pcisecuritystandards.org",
    "law.",
    "laws.",
    "legislation.",
    "ly.gov.tw",
    "ppg.ly.gov.tw",
    "consumer.org",
    "consumers.org",
)
trusted_company_path_terms = (
    "/legal",
    "/terms",
    "/privacy",
    "/policy",
    "/policies",
    "/security",
    "/trust",
    "/compliance",
    "/docs",
    "/documentation",
    "/guidelines",
    "/contents/terms",
)


def usable_source_url(url: str) -> bool:
    parsed = urlparse(clean_text(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in excluded_source_hosts:
        return False
    if path in excluded_source_paths:
        return False
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc)


def credible_source_url(url: str) -> bool:
    if not usable_source_url(url):
        return False
    parsed = urlparse(clean_text(url))
    host = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "/").lower()
    host_blob = f"{host}/"
    if any(term in path for term in low_credibility_path_terms):
        return any(term in host_blob for term in trusted_host_keywords)
    if any(term in host_blob for term in trusted_host_keywords):
        return True
    return any(term in path for term in trusted_company_path_terms)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_source_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: f"{m.group(1).strip()}: {m.group(2).strip()}",
        text,
    )
    text = text.replace("<", "").replace(">", "")
    return text.strip()


def source_urls(values: Any) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]

    urls: List[str] = []
    seen = set()
    for value in values:
        text = clean_source_text(value)
        if not text:
            continue
        for url in re.findall(r"https?://[^\s,，)）<>'\"]+", text):
            clean_url = url.rstrip(".,;:。；：")
            if clean_url and credible_source_url(clean_url) and clean_url not in seen:
                urls.append(clean_url)
                seen.add(clean_url)
    return urls


def source_title_from_url(url: str) -> str:
    text = clean_text(url)
    parsed = urlparse(text)
    host = parsed.netloc.lower().replace("www.", "")
    path = unquote(parsed.path or "")
    if path:
        filename = path.rstrip("/").split("/")[-1]
        if filename:
            return f"{host} / {filename}" if host else filename
    return host or text


def source_records(values: Any) -> List[Dict[str, str]]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]

    rows: List[Dict[str, str]] = []
    seen = set()
    for value in values:
        title = ""
        url = ""
        if not isinstance(value, dict):
            continue
        title = clean_source_text(value.get("title"))
        raw_url = value.get("url")
        source_type = clean_source_text(value.get("type"))
        if source_type == "file":
            url = clean_source_text(raw_url)
            if not url:
                continue
            if not title:
                title = source_title_from_url(url)
            filename = url.rstrip("/").split("/")[-1].lower()
            key = f"file:{filename or url.lower()}"
            if key in seen:
                continue
            rows.append({"title": title, "url": url, "type": "file"})
            seen.add(key)
            continue
        urls = source_urls(raw_url)
        url = urls[0] if urls else ""
        if not url or not credible_source_url(url):
            continue
        if not title or source_urls(title):
            title = source_title_from_url(url)
        key = url
        if key in seen:
            continue
        row = {
            "title": title,
            "url": url,
            "type": "web",
        }
        source_id = clean_source_text(value.get("id"))
        if source_id:
            row["id"] = source_id
        rows.append(row)
        seen.add(key)
    return rows


def requires_url_sources(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if source_records(payload.get("sources")):
        return True
    for field in trace_fields:
        for item in payload.get(field) or []:
            if not isinstance(item, dict):
                continue
            evidence_type = clean_text(item.get("evidence_type") or item.get("source_type")).lower()
            if evidence_type in {"web", "url", "external", "external_source", "research"}:
                return True
            source = clean_source_text(item.get("source"))
            if source_urls(source):
                return True
    return False


def has_research_content(payload: Dict[str, Any]) -> bool:
    return any(bool(payload.get(field)) for field in research_fields)


def enforce_research_boundaries(
    payload: Dict[str, Any],
    *,
    allowed_requirement_ids: set[str] | None = None,
    context_source: str = "",
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    source_ref = clean_source_text(context_source)
    for field in trace_fields:
        rows = payload.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            refs = requirement_refs(row.get("related_requirement_ids"))
            if allowed_requirement_ids is not None:
                refs = [ref for ref in refs if ref in allowed_requirement_ids]
            row["related_requirement_ids"] = refs
            if source_ref:
                row["source"] = source_ref
    return payload


def compact_list(values: Any) -> List[Any]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]

    rows: List[Any] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            row = {str(k): v for k, v in value.items() if v not in (None, "", [], {})}
            if not row:
                continue
            key = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen:
                rows.append(row)
                seen.add(key)
            continue
        text = clean_source_text(value)
        if not text or text in seen:
            continue
        rows.append(text)
        seen.add(text)
    return rows


def requirement_refs(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    refs: List[str] = []
    seen = set()
    for value in values:
        ref = clean_text(value)
        if not ref or ref in seen:
            continue
        refs.append(ref)
        seen.add(ref)
    return refs


def research_items(values: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for value in compact_list(values):
        if not isinstance(value, dict):
            continue
        text = clean_text(value.get("text"))
        if not text:
            continue
        source = clean_source_text(value.get("source"))
        row = {
            "text": text,
            "related_requirement_ids": requirement_refs(value.get("related_requirement_ids")),
        }
        if source:
            row["source"] = source
        source_ids = requirement_refs(value.get("source_ids"))
        if source_ids:
            row["source_ids"] = source_ids
        source_paths = requirement_refs(value.get("source_paths"))
        if source_paths:
            row["source_paths"] = source_paths
        trace_reason = clean_text(value.get("trace_reason"))
        if trace_reason:
            row["trace_reason"] = trace_reason
        evidence_type = clean_text(value.get("evidence_type") or value.get("source_type"))
        if evidence_type:
            row["evidence_type"] = evidence_type

        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            rows.append(row)
            seen.add(key)
    return rows


def resolve_web_source_ids(values: Any, valid_source_ids: list[str]) -> List[str]:
    """Resolve only IDs that can be proven from the current source inventory."""
    valid_ids = list(
        dict.fromkeys(
            clean_text(value)
            for value in valid_source_ids
            if clean_text(value)
        )
    )
    requested = requirement_refs(values)
    if not requested:
        return valid_ids if len(valid_ids) == 1 else []

    resolved: List[str] = []
    for source_id in requested:
        if source_id in valid_ids:
            resolved.append(source_id)
            continue
        match = re.fullmatch(r"SRC-(\d+)", source_id, flags=re.IGNORECASE)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(valid_ids):
                resolved.append(valid_ids[index])
                continue
        return []
    return list(dict.fromkeys(resolved))


def evidence_source_inventory(source: Dict[str, Any]) -> tuple[set[str], set[str]]:
    raw_sources = source.get("sources") if isinstance(source.get("sources"), list) else []
    valid_web_source_ids = {
        clean_text(item.get("id"))
        for item in raw_sources
        if isinstance(item, dict)
        and clean_text(item.get("id"))
        and credible_source_url(clean_text(item.get("url")))
    }
    valid_file_paths = {
        clean_text(item.get("url"))
        for item in raw_sources
        if isinstance(item, dict)
        and clean_text(item.get("type")).lower() == "file"
        and clean_text(item.get("url"))
    }
    return valid_web_source_ids, valid_file_paths


def validate_traceable_evidence(source: Dict[str, Any]) -> None:
    valid_web_source_ids, valid_file_paths = evidence_source_inventory(source)
    ordered_web_source_ids = [
        clean_text(item.get("id"))
        for item in (source.get("sources") or [])
        if isinstance(item, dict)
        and clean_text(item.get("id")) in valid_web_source_ids
    ]
    for field in trace_fields:
        for index, row in enumerate(source.get(field) or [], 1):
            if not isinstance(row, dict):
                continue
            evidence_type = clean_text(row.get("evidence_type") or row.get("source_type")).lower()
            if evidence_type == "web":
                source_ids = requirement_refs(row.get("source_ids"))
                resolved_ids = resolve_web_source_ids(source_ids, ordered_web_source_ids)
                if not resolved_ids:
                    invalid_ids = [
                        source_id
                        for source_id in source_ids
                        if source_id not in valid_web_source_ids
                    ]
                    detail = ", ".join(invalid_ids) if invalid_ids else "<empty>"
                    raise ValueError(
                        f"{field}[{index}] web source_ids invalid: {detail}"
                    )
                row["source_ids"] = resolved_ids
            elif evidence_type == "project_document":
                source_paths = requirement_refs(row.get("source_paths"))
                invalid_paths = [path for path in source_paths if path not in valid_file_paths]
                if not source_paths or invalid_paths:
                    detail = ", ".join(invalid_paths) if invalid_paths else "<empty>"
                    raise ValueError(f"{field}[{index}] project_document source_paths invalid: {detail}")


def clean_research_result(raw: Any, *, context_source: str = "") -> Dict[str, Any]:
    _ = context_source
    source = raw.get("research_evidence") if isinstance(raw, dict) and isinstance(raw.get("research_evidence"), dict) else {}
    return clean_research_payload(source)


def clean_feedback(raw: Any, *, context_source: str = "") -> Dict[str, Any]:
    _ = context_source
    if not isinstance(raw, dict) or not isinstance(raw.get("feedback"), dict):
        return {}
    return clean_research_payload(raw.get("feedback") or {})


def clean_research_payload(source: Dict[str, Any]) -> Dict[str, Any]:
    validate_traceable_evidence(source)
    result = {
        field: (
            research_items(source.get(field))
            if field in trace_fields
            else source_records(source.get(field))
        )
        for field in research_fields
    }

    return result if has_research_content(result) else {}
