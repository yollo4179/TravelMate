"""관찰의 주체와 핵심·보조 이동 관계를 독립적으로 보존하는 선택 계약."""
from .v5_contextual_prompt import INSTRUCTIONS as V5_INSTRUCTIONS

PROMPT_VERSION = "contextual-independent-relations-v7"
INSTRUCTIONS = V5_INSTRUCTIONS + """

These rules supersede earlier route-role examples when preserving a relation.
The code supplies exact sentence/paragraph spans. Do not split or rewrite them merely because two places occur.
content_kind (landscape/facility/movement/other) describes the main observation. It does NOT restrict relations.
Keep an actual movement relation even inside a landscape, facility or other chunk.
Every relation has type=movement and importance=primary or supporting. Primary means the route is central;
supporting means it is incidental to the main observation. Both must be preserved and can be searched.
place_refs.subject is the owner of the main observation, NOT automatically every movement endpoint.
Never promote a destination to subject just to make a route searchable. Preserve it as mentioned when appropriate.
Example: 'A has beautiful night views, and after viewing one can walk to B.'
Keep ONE landscape chunk: A=subject, B=mentioned; keep A-to-B movement as supporting.
Do not attribute A's scenery or facilities to B. The relation is indexed separately from observation ownership.
For a movement-only chunk choose its actual subject without forcing all endpoints to share that role.
Known endpoint IDs and exact names must come from supplied places and be preserved in place_refs with their actual roles.
Unknown endpoint IDs are null; never substitute a target ID for an unknown park.
Each relation.evidence has absolute Unicode start/end offsets in the SAME source and an exact quote;
it must lie wholly within THIS supplied span and cover the complete movement assertion and its conditions.
Extract only the route clause when scenery precedes it. Do not include unrelated scenery in relation evidence.
Each condition (stairs/distance/duration/other) quotes exact text inside that relation's evidence.
Do not infer easy, convenient, flat, short or safe access; preserve stated evidence only.
Do not import another chunk's route or conditions. If no route is supported, return relations=[].
Keep uncertain relationships unassigned rather than inventing participants, direction or evidence.
Return all requested fields. hypothetical_questions=[]; do not search the web.
"""
