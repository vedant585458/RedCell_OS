"""CISO intelligence layer for RedCell_OS."""

from .intake_interpreter import (
    CisoIntakeInterpreter,
    CisoInterpretationResult,
    InterpretedObjective,
)
from .prompts import CISO_INTERPRETATION_USER_PROMPT, CISO_SYSTEM_PROMPT

__all__ = [
    "CisoIntakeInterpreter",
    "CisoInterpretationResult",
    "InterpretedObjective",
    "CISO_SYSTEM_PROMPT",
    "CISO_INTERPRETATION_USER_PROMPT",
]
