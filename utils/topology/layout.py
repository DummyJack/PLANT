from typing import Tuple


def trace_topology_rects_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], padding: float = 0) -> bool:
    return not (
        a[2] + padding <= b[0]
        or b[2] + padding <= a[0]
        or a[3] + padding <= b[1]
        or b[3] + padding <= a[1]
    )


