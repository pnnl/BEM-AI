from __future__ import annotations

from enum import Enum


class ConfidenceLevel(str, Enum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    VALIDATED = "validated"
    PROMOTED = "promoted"

