"""FFI compliance checker: ISO 26262 Freedom From Interference checks for AUTOSAR."""

from .arxml_parser import parse_arxml
from .model import Asil, EcuModel

__all__ = ["parse_arxml", "Asil", "EcuModel"]
