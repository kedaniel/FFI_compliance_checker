"""Explanations WITHOUT an LLM, from templates.

Two uses:
  * the fallback when no LLM is reachable: the report still has a readable explanation;
  * `--demo`: lets you see the whole pipeline on a laptop that has no model installed yet.

They are plain Python string formatting over the finding, so they are always grounded.
"""

from __future__ import annotations

from ..rules.model import Finding
from .schema import Explanation

WHY = {
    "R1_placement": "Data in the wrong partition is not protected by the MPU from code with a "
                    "different integrity level, which breaks freedom from interference.",
    "R2_alignment": "The MPU rounds a misaligned region, so it may protect more or less memory "
                    "than intended.",
    "R3_guard_pad": "Without a gap, rounding of MPU regions can let QM and ASIL regions overlap.",
    "R4_xref": "A QM module that writes ASIL data would be interference. The map cannot tell a "
               "read from a write.",
    "R5_wildcard": "The wildcard group is shared and writable by several partitions, so ASIL data "
                   "there is unprotected.",
}
FIX = {
    "R1_placement": "Move {obj} to a group owned by a partition that lists its module and has "
                    "at least its ASIL, normally by fixing its MemMap section or the partition's "
                    "module list.",
    "R2_alignment": "Align the region boundary {obj} to the MPU granularity in the linker script.",
    "R3_guard_pad": "Add or enlarge the guard pad {obj} so the gap meets the required minimum.",
    "R4_xref": "Check in the code of {user} whether it only reads {obj} or also writes it.",
    "R5_wildcard": "Add the missing MemMap section for {obj} so it lands in its own partition group.",
}
QUESTIONS = {
    "R4_xref": ["Does the referencing module only read this data?",
                "If it writes, is it allowed through a safe interface such as E2E-protected communication?"],
}


def template_explanation(f: Finding) -> Explanation:
    obj = f.symbol or f.group or "the object"
    return Explanation(
        summary=f.detail[:400] if len(f.detail) >= 10 else f"{f.rule} reported for {obj}.",
        why_it_matters=WHY.get(f.rule, "This may break freedom from interference."),
        suggested_fix=FIX.get(f.rule, "Review {obj} against the rule.").format(obj=obj, user=f.referenced_by or "the referencing module"),
        questions_to_check=QUESTIONS.get(f.rule, []),
        evidence_used=[e.source for e in f.evidence[:2]],
    )
