"""관계 인용의 위치 계산을 서버에 맡기는 선택 계약. v7은 보존한다."""
from .v7_contextual_prompt import INSTRUCTIONS as V7_INSTRUCTIONS

PROMPT_VERSION = "contextual-server-evidence-v8"
INSTRUCTIONS = V7_INSTRUCTIONS.replace(
    "Each relation.evidence has absolute Unicode start/end offsets in the SAME source and an exact quote;\n"
    "it must lie wholly within THIS supplied span and cover the complete movement assertion and its conditions.",
    "Each relation.evidence contains ONLY an exact quote copied from THIS supplied span.chunk_text.\n"
    "Do NOT return or calculate evidence.start/end. The server computes these coordinates.\n"
    "Choose a quote occurring exactly once within THIS chunk and covering the complete movement assertion and conditions.\n"
    "If the evidence cannot be quoted unambiguously, keep the relation unassigned; never rewrite or normalize the quote.",
)
