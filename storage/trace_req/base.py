from typing import Any, Dict, List

from .collector import collect_trace_req_rows
from .indexes import build_trace_req_indexes
from .normalizer import normalize_trace_req_rows
from .schema import public_trace_req_row


def build_trace_req(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    indexes = build_trace_req_indexes(data)
    rows = collect_trace_req_rows(data, indexes)
    rows = normalize_trace_req_rows(rows, indexes)
    public_rows = [public_trace_req_row(row) for row in rows]
    data["trace_req"] = public_rows
    return public_rows
