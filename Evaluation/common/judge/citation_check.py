"""Check judge schema, applicability and exact citations against supplied evidence."""
from typing import Any
from .structured_output import CRITERIA, JUDGE_SCHEMA


def validate_judge_output(document: dict[str, Any], output_text: str, source_text: str) -> None:
    from jsonschema import Draft202012Validator
    Draft202012Validator(JUDGE_SCHEMA).validate(document)
    judgments = document["judgments"]
    if len(judgments) != len(CRITERIA) or {item["criterion"] for item in judgments} != set(CRITERIA):
        raise ValueError("Judge omitted or duplicated criteria")
    for item in judgments:
        if item["applicable"] != (item["score"] is not None) or not item["reason"].strip():
            raise ValueError("Invalid judge applicability or rationale")
        for name, available in (("output_quote", output_text), ("source_quote", source_text)):
            if item[name] is not None and (not item[name].strip() or item[name] not in available):
                raise ValueError("Judge citation is not an exact substring of supplied evidence")
