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


# ========
# Defines usable source URL function for this module workflow.
# ========
def usable_source_url(url: str) -> bool:
    parsed = urlparse(clean_text(url))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in excluded_source_hosts:
        return False
    if path in excluded_source_paths:
        return False
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc)


# ========
# Defines credible source URL function for this module workflow.
# ========
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


# ========
# Defines clean text function for this module workflow.
# ========
def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


# ========
# Defines clean source text function for this module workflow.
# ========
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


# ========
# Defines source urls function for this module workflow.
# ========
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


# ========
# Defines source title from URL function for this module workflow.
# ========
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


# ========
# Defines source records function for this module workflow.
# ========
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
        rows.append({"title": title, "url": url})
        seen.add(key)
    return rows


# ========
# Defines requires URL sources function for this module workflow.
# ========
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


# ========
# Defines has research content function for this module workflow.
# ========
def has_research_content(payload: Dict[str, Any]) -> bool:
    return any(bool(payload.get(field)) for field in research_fields)


# ========
# Defines compact list function for this module workflow.
# ========
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


# ========
# Defines requirement refs function for this module workflow.
# ========
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


# ========
# Defines research items function for this module workflow.
# ========
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


# ========
# Defines clean research result function for this module workflow.
# ========
def clean_research_result(raw: Any, *, context_source: str = "") -> Dict[str, Any]:
    _ = context_source
    source = raw.get("research_evidence") if isinstance(raw, dict) and isinstance(raw.get("research_evidence"), dict) else {}
    result: Dict[str, Any] = {}

    result["findings"] = research_items(source.get("findings"))
    result["sources"] = source_records(source.get("sources"))
    result["constraints"] = research_items(source.get("constraints"))
    result["risks"] = research_items(source.get("risks"))
    result["recommendations"] = research_items(source.get("recommendations"))
    return result if has_research_content(result) else {}


# ========
# Defines clean feedback function for this module workflow.
# ========
def clean_feedback(raw: Any, *, context_source: str = "") -> Dict[str, Any]:
    _ = context_source
    if not isinstance(raw, dict) or not isinstance(raw.get("feedback"), dict):
        return {}
    source = raw.get("feedback") or {}
    result = {}

    for field in research_fields:
        if field in trace_fields:
            result[field] = research_items(source.get(field))
        else:
            result[field] = source_records(source.get(field))

    return result if has_research_content(result) else {}
