"""What the LLM is asked to produce, as a Pydantic model.

Pydantic AI turns this class into a JSON schema for the model and validates the answer
against it. A malformed or incomplete answer is rejected and the model is asked again.

Notice what is NOT here: severity, rule id, "is this a real problem?". The LLM explains a
verdict that deterministic code already made, it never makes or changes one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Explanation(BaseModel):
    summary: str = Field(
        description="One or two short sentences: what is wrong, in plain language.",
        min_length=10, max_length=400)
    why_it_matters: str = Field(
        description="Why this can break freedom from interference (ISO 26262), in one or two sentences.",
        min_length=10, max_length=500)
    suggested_fix: str = Field(
        description="Concrete next step for the engineer, based only on the facts given.",
        min_length=10, max_length=500)
    questions_to_check: list[str] = Field(
        default_factory=list, max_length=4,
        description="Things the engineer should verify because the facts are not enough to be sure.")
    evidence_used: list[str] = Field(
        default_factory=list,
        description="The 'source' values of the evidence items this explanation relies on, copied exactly.")
