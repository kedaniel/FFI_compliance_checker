"""Check an explanation against the finding it is about. Deterministic, no LLM.

LLMs sometimes invent plausible names. In a safety context an invented symbol in an
explanation is worse than no explanation, so every identifier-like thing in the answer must
come from the finding. If not, the answer is rejected and the model must try again; if it keeps
failing, the finding is reported without an explanation.

What counts as identifier-like:
    - words with an underscore, e.g. SafetyMon_State, ASIL_D_DATA_tc0
    - hex numbers, e.g. 0x6000556c
    - file names, e.g. synthetic_tc39x.map
"""

from __future__ import annotations

import re

from ..rules.model import Finding
from .prompt import finding_block
from .schema import Explanation

IDENTIFIER = re.compile(r"\b\w*_\w*\b|\b0x[0-9a-fA-F]+\b|\b[\w-]+\.(?:c|h|o|map|json|arxml)\b")
WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|0x[0-9a-fA-F]+|[\w-]+\.(?:c|h|o|map|json|arxml)")


def _explanation_text(x: Explanation) -> str:
    return " ".join([x.summary, x.why_it_matters, x.suggested_fix, *x.questions_to_check])


def grounding_problems(x: Explanation, f: Finding) -> list[str]:
    """Return a list of problems. Empty list = the explanation is grounded in the finding."""
    known = finding_block(f).lower()
    problems: list[str] = []

    for token in sorted(set(IDENTIFIER.findall(_explanation_text(x)))):
        if token.lower() not in known:  # substring: "ASIL_D" is fine inside "ASIL_D_Core0"
            problems.append(f"'{token}' does not appear in the finding")

    allowed_sources = {e.source for e in f.evidence}
    for src in x.evidence_used:
        if src not in allowed_sources:
            problems.append(f"evidence_used '{src}' is not one of the finding's evidence sources")
    return problems
