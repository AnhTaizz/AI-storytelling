"""Offline oracle projection from canonical gold to Draft V1.1.

This module is for representability testing only. It does not extract, call a
provider, score model output, or participate in the production compiler path.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.story_extraction.draft_compiler_v1_1 import DRAFT_VERSION
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1


def canonical_gold_to_draft_v1_1(
    gold: dict[str, Any], context: Any
) -> tuple[dict[str, Any], dict[str, str]]:
    """Project authored gold to V1.1 by removing only model-facing mention links."""
    draft_v1, mapping = canonical_gold_to_draft_v1(gold, context)
    projected = deepcopy(draft_v1)
    projected["draft_version"] = DRAFT_VERSION
    for mention in projected["mentions"]:
        mention.pop("evidence_handle", None)
    return projected, mapping
