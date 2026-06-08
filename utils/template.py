# Handles template logic for shared utility behavior for the Plant runtime.
from typing import Any


# ========
# Defines render template function for this module workflow.
# ========
def render_template(template: str, context: dict[str, Any]) -> str:
    out: list[str] = []
    i = 0
    n = len(template)
    while i < n:
        ch = template[i]
        if ch == "{" and i + 1 < n and template[i + 1] == "{":
            out.append("{")
            i += 2
            continue
        if ch == "}" and i + 1 < n and template[i + 1] == "}":
            out.append("}")
            i += 2
            continue
        if ch != "{":
            out.append(ch)
            i += 1
            continue
        end = find_expr_end(template, i + 1)
        if end < 0:
            out.append(ch)
            i += 1
            continue
        expr = template[i + 1 : end].strip()
        try:
            out.append(str(eval(expr, {}, dict(context))))
        except Exception:
            out.append("{" + template[i + 1 : end] + "}")
        i = end + 1
    return "".join(out)


# ========
# Defines find expr end function for this module workflow.
# ========
def find_expr_end(text: str, start: int) -> int:
    quote = ""
    escape = False
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            if ch == "}" and depth == 0:
                return i
            depth = max(0, depth - 1)
    return -1
