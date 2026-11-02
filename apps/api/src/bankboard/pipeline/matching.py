from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=2048)
def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def matches(match_type: str, pattern: str, value: str) -> bool:
    if not value:
        return False
    if match_type == "exact":
        return value == pattern
    if match_type == "prefix":
        return value.startswith(pattern)
    if match_type == "contains":
        # must start on a word boundary: "FEE" must not match "COFFEE", "MCDONALD" matches "MCDONALDS"
        return f" {value}".find(f" {pattern}") >= 0
    if match_type == "regex":
        return _regex(pattern).search(value) is not None
    return False
