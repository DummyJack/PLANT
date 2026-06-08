# DEPRECATED: unused duplicate of the root `storage` package. See README.md.
# Initializes the storage package.
from .artifact import compact_markdown_context
from .json import json_dump_no_scientific, json_dumps_no_scientific, parse_first_json
from .manager import Store

__all__ = [
    "Store",
    "compact_markdown_context",
    "json_dump_no_scientific",
    "json_dumps_no_scientific",
    "parse_first_json",
]
