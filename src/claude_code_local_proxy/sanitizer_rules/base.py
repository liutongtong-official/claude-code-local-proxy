"""Shared types for sanitizer rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Mode = Literal["off", "observe", "normalize"]


@dataclass(frozen=True)
class SanitizeStats:
    """Summary of marker observations made while walking a JSON payload."""

    date_lines: int = 0
    apostrophe_variants: int = 0
    slash_dates: int = 0
    replacements: int = 0

    @property
    def observed(self) -> bool:
        return self.date_lines > 0

    @property
    def changed(self) -> bool:
        return self.replacements > 0

    def __add__(self, other: SanitizeStats) -> SanitizeStats:
        return SanitizeStats(
            date_lines=self.date_lines + other.date_lines,
            apostrophe_variants=self.apostrophe_variants + other.apostrophe_variants,
            slash_dates=self.slash_dates + other.slash_dates,
            replacements=self.replacements + other.replacements,
        )


class SanitizerRule(Protocol):
    """A string-level sanitizer rule used by the JSON sanitizer pipeline."""

    name: str

    def apply(self, text: str, mode: Mode) -> tuple[str, SanitizeStats]:
        """Return sanitized text and observation statistics."""
        ...
