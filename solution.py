"""Official participant entry point; standard library only, no kit imports."""
from knowledge.system import KnowledgeSystem


def build() -> KnowledgeSystem:
    return KnowledgeSystem()
