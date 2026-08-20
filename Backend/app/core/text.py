"""Shared text utilities: normalization, tokenization, stopwords.

Used by both the Markdown knowledge retriever and the advocate-name extractor,
so tokenization behaves identically everywhere in the pipeline.
"""

import re

_STOPWORDS: frozenset[str] = frozenset(
    """
    a an the is are was were be been being do does did have has had
    i you he she it we they me him her us them my your his its our their
    what which who whom this that these those am will would shall should
    can could may might must ought
    of in on at to for from by with about against between into through
    during before after above below up down out off over under again
    further then once here there when where why how all any both each
    few more most other some such no nor not only own same so than too very
    and but or if because as until while
    please help need want know tell explain
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']*|\d+")


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, hyphenated words kept whole."""
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def keywords(text: str, *, min_len: int = 2, max_keywords: int | None = None) -> list[str]:
    """Extract content keywords: tokenize, drop stopwords and very short tokens.

    Order-preserving with duplicates removed (first occurrence kept), so callers
    that care about "most important first" (e.g. a query analysis result) are
    not silently reordered.
    """
    seen: dict[str, None] = {}
    for tok in tokenize(text):
        if len(tok) < min_len or tok in _STOPWORDS:
            continue
        seen.setdefault(tok, None)
    result = list(seen.keys())
    if max_keywords is not None:
        result = result[:max_keywords]
    return result


def title_case_tokens(text: str) -> list[str]:
    """Split on whitespace, keep only tokens that look like Title-Case name parts."""
    return [t for t in re.split(r"\s+", text.strip()) if t]
