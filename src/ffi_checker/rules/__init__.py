"""Milestone 4: the memory-FFI rule engine."""

from .compare import Comparison, compare
from .memory import ALL_RULES, run_rules
from .model import Evidence, Finding

__all__ = ["run_rules", "ALL_RULES", "Finding", "Evidence", "compare", "Comparison"]
