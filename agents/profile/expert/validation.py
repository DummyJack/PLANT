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

external_source_terms = (
    "法規",
    "法律",
    "條例",
    "規範",
    "標準",
    "官方",
    "第三方",
    "合規",
    "稽核",
    "金管會",
    "NCC",
    "PCI",
    "ISO",
    "GDPR",
    "PDPA",
    "FSC",
    "regulation",
    "law",
    "standard",
    "official",
    "compliance",
    "audit",
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
    if "law.banking.gov.tw" in host:
        return "電子支付相關法規"
    if "lawreview.law.ncku.edu.tw" in host:
        return "金融與電子支付法制研究資料"
    if "mjib.gov.tw" in host:
        return "洗錢防制相關規範"
    if "leaven-china.com" in host:
        return "跨境金流與合規實務文章"
    if "pdpc.gov.tw" in host:
        return "個人資料保護相關指引"
    if "informationsecurity.com.tw" in host:
        return "資訊安全管理實務參考"
    if "consumer.org.hk" in host:
        return "外送平台消費爭議案例"
    if "ly.gov.tw" in host or "ppg.ly.gov.tw" in host:
        return "立法院法規與政策資料"
    if "dlacp.gov.taipei" in host:
        return "臺北市消費者保護公開資訊"
    if "immigration.gov.tw" in host:
        return "政府移民與個資公開資訊"
    if "aia.kcg.gov.tw" in host:
        return "高雄市政府公開資訊"
    if "gov.tw" in host:
        return "政府機關公開資料"
    if "epicor.com" in host:
        return "GDPR 合規參考"
    if "kuritataiwan.com.tw" in host:
        return "個人資料保護管理政策"
    if path:
        filename = path.rstrip("/").split("/")[-1]
        if filename:
            return filename
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
        if isinstance(value, dict):
            title = clean_source_text(value.get("title") or value.get("name") or value.get("label"))
            raw_url = value.get("url") or value.get("link") or value.get("href") or value.get("source")
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
        else:
            urls = source_urls(value)
            url = urls[0] if urls else ""
            title = clean_source_text(value)
            if url and title == url:
                title = ""
        if not url or not credible_source_url(url):
            continue
        if not title:
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

    for field in trace_fields:
        for item in payload.get(field) or []:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                [
                    clean_text(item.get("text")),
                    clean_text(item.get("source")),
                ]
            )
            lowered = text.lower()
            if any(term.lower() in lowered for term in external_source_terms):
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
        if isinstance(value, dict):
            text = clean_text(value.get("text") or value.get("finding") or value.get("note"))
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
        else:
            text = clean_text(value)
            if not text:
                continue
            row = {"text": text, "related_requirement_ids": []}

        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            rows.append(row)
            seen.add(key)
    return rows


# ========
# Defines clean research result function for this module workflow.
# ========
def clean_research_result(raw: Any, *, context_source: str = "") -> Dict[str, Any]:
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
