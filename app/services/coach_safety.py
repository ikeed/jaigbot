from __future__ import annotations

import re
from typing import List

# Compiled regex patterns identical to the inline logic in app.main
# Medication terms and dosage/interval patterns
_MED_TERMS = r"acetaminophen|ibuprofen|paracetamol|tylenol|antibiotic|amoxicillin|penicillin|azithromycin"
_ADVICE_RE = re.compile(
    rf"\b(((you|he|she)\s+(should|needs\s+to|must))|((give|take)\s+({_MED_TERMS}))|\d+\s*mg|every\s+\d+\s+(hours|days))\b",
    re.I,
)
_IGNORE_RE = re.compile(r"\btake\s+home\b", re.I)


def detect_advice_patterns(text: str) -> List[str]:
    """Detects clinical advice-like patterns in a string.

    Behavior-preserving extraction from app.main: returns a list containing
    "clinical_advice_like" when medication/dose/interval cues are present
    and the benign phrase "take home" is not present. Returns an empty list
    otherwise.
    """
    lower = (text or "").lower()
    hits: List[str] = []
    if _ADVICE_RE.search(lower) and not _IGNORE_RE.search(lower):
        hits.append("clinical_advice_like")
    return hits
