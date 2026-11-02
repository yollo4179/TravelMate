"""코드가 잘라 전달한 원문을 우선 읽는 후속 지시문. 기존 v4는 보존한다."""
from .v4_contextual_prompt import INSTRUCTIONS as V4_INSTRUCTIONS

PROMPT_VERSION = "contextual-source-spans-v5"

INSTRUCTIONS = V4_INSTRUCTIONS.replace(
    "1. Locate the exact quotation source.text[start:end], counting Unicode codepoints. The supplied offsets determine its boundaries.",
    "1. Read the supplied span.chunk_text as the exact quotation, already sliced and verified by code.\n"
    "   Do not calculate character positions or locate a different passage in the full document.\n"
    "   source_id/start/end are immutable provenance coordinates; copy them unchanged, not as a reading task.",
)
