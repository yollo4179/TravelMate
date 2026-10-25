"""The unchanged structured output contract for the optional MD judge."""
CRITERIA = ("intent_alignment", "persona_consistency", "grounded_claims", "tool_outcome_communication")
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"judgments": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "criterion": {"type": "string", "enum": list(CRITERIA)},
                "applicable": {"type": "boolean"},
                "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 3},
                "reason": {"type": "string"},
                "output_quote": {"type": ["string", "null"]},
                "source_quote": {"type": ["string", "null"]},
            },
            "required": ["criterion", "applicable", "score", "reason", "output_quote", "source_quote"],
            "additionalProperties": False,
        },
    }},
    "required": ["judgments"], "additionalProperties": False,
}
