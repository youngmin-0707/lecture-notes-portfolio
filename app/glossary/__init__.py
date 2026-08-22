"""용어집(glossary) 관련 모듈 (§2.2, §3.3)."""

from __future__ import annotations

from app.glossary.correction import (
    build_initial_prompt,
    correct_transcript_text,
    fetch_applicable_terms,
)
from app.glossary.default_terms import DEFAULT_GLOSSARY_TERMS

__all__ = [
    "DEFAULT_GLOSSARY_TERMS",
    "build_initial_prompt",
    "correct_transcript_text",
    "fetch_applicable_terms",
]
