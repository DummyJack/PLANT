from typing import Any, Dict, List


class DocumentorDrTracePublicMixin:
    @classmethod
    def public_dr_requirement_context(cls, requirement: Dict[str, Any]) -> Dict[str, Any]:
        public = dict(requirement)
        public.pop("trace_repair_reference_graph", None)
        graph = public.get("trace_graph")
        if isinstance(graph, dict) and "all_nodes" in graph:
            public["trace_graph"] = {key: value for key, value in graph.items() if key != "all_nodes"}
        return public

    @classmethod
    def public_dr_requirement_contexts(cls, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [cls.public_dr_requirement_context(req) for req in requirements]

    @staticmethod
    def trace_target_aliases(requirement: Dict[str, Any]) -> set[str]:
        return {
            str(requirement.get("id") or "").strip(),
            str(requirement.get("srs_id") or "").strip(),
        } - {""}
