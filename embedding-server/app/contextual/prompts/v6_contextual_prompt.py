"""관찰의 귀속과 장소 간 이동 관계를 구분하는 선택 지시문."""
from .v5_contextual_prompt import INSTRUCTIONS as V5_INSTRUCTIONS

PROMPT_VERSION = "contextual-observation-relations-v6"
INSTRUCTIONS = V5_INSTRUCTIONS + """

The supplied spans were cut at sentence/paragraph boundaries by code. NEVER split a span because two place names occur.
Classify content_kind independently of place roles: landscape, facility, movement, or other.
subject identifies a core place, NOT an observation category. A scene or facility belongs only to its observed owner.
If a span's main topic is movement, preserve the complete origin-to-destination relationship as ONE movement chunk.
For example, 'From Park A I went down the stairs to Park B' describes an A-to-B route, not A's scenery or B's parking.
Return relations with origin and destination names, and their supplied place IDs when known; use null for an unavailable ID.
Unknown parks NEVER inherit a supplied park's ID. Use exact supplied names for known endpoint IDs.
Each condition contains its kind (stairs/distance/duration/other) and an EXACT quote present in THIS chunk_text.
Do not infer easy, convenient, step-free, short or safe access from movement alone. Retain stairs, distance and duration as stated.
For a movement span, all known endpoint IDs are subject participants so the route can be retrieved from either endpoint.
This does not attribute any scenery or facility to both endpoints. Other incidental places remain mentioned/view_target.
If movement or its endpoints cannot be resolved from this span and the SAME document, withhold attribution rather than invent it.
Unattributed movement may retain unknown endpoint names in relations but has no subject and is not indexed.
For non-movement spans return relations=[]. Do not append a route merely because its document contains a route elsewhere.
If one unsplittable span mixes another park's scenery with the target's route/facility, do not index the foreign observation
under the target: use empty place_refs/entities when the exact span cannot be given a safe single observation scope.
Return all original response fields plus content_kind and relations, exactly as the requested schema specifies.
"""
