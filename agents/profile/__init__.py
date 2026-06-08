# Initializes package exports and module loading.

__all__ = [
    "UserAgent",
    "AnalystAgent",
    "ExpertAgent",
    "MediatorAgent",
    "ModelerAgent",
    "DocumentorAgent",
]


def __getattr__(name):
    if name == "UserAgent":
        from .user import UserAgent

        return UserAgent
    if name == "AnalystAgent":
        from .analyst import AnalystAgent

        return AnalystAgent
    if name == "ExpertAgent":
        from .expert import ExpertAgent

        return ExpertAgent
    if name == "MediatorAgent":
        from .mediator import MediatorAgent

        return MediatorAgent
    if name == "ModelerAgent":
        from .modeler import ModelerAgent

        return ModelerAgent
    if name == "DocumentorAgent":
        from .documentor import DocumentorAgent

        return DocumentorAgent
    raise AttributeError(name)
