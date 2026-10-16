"""Stage 2 of the pipeline: normalize tokens into index terms.

- Zero-width joiners (U+200C ZWNJ, U+200D ZWJ) are removed. They only change
  how a word is *rendered*, but 17% of passages contain them, and without
  removal విక్రమ్\u200c (with ZWNJ) and విక్రమ్ (without) would be different terms.
- A Devanagari nukta (U+093C) that does not follow a Devanagari letter is
  removed. The collection has one, stuck to the front of a Telugu word
  (<U+093C>కేశవ); a real Hindi nukta, as in जड़ता, is kept.
- Unicode NFKC composes equivalent character sequences into one form
  (e.g. ె + ౖ  ->  ై ) and folds full-width Latin letters and digits.
- Telugu digits ౦-౯ become ASCII 0-9, so ౨౦౧౧ and 2011 match.
- Latin letters are lowercased (about 10% of passages contain English words).
- Tokens left with no letters or numbers are dropped.

No suffix stripping or stop-word removal yet: ఇంటికి ("to the house") and
ఇల్లు ("house") are still different terms. Measuring that gap and closing
it comes in a later stage.
"""

import unicodedata
from dataclasses import dataclass

from .tokenizer import ZERO_WIDTH_JOINERS, Token, tokenize

TELUGU_DIGITS = str.maketrans("౦౧౨౩౪౫౬౭౮౯", "0123456789")
DEVANAGARI_NUKTA = "\u093c"


@dataclass(frozen=True)
class Term:
    term: str  # normalized form stored in the index
    token: Token  # the original token it came from (surface + offsets)


def is_devanagari(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f"


def drop_stray_nukta(text: str) -> str:
    return "".join(
        ch for i, ch in enumerate(text) if ch != DEVANAGARI_NUKTA or (i > 0 and is_devanagari(text[i - 1]))
    )


def normalize_text(text: str) -> str:
    text = "".join(ch for ch in text if ch not in ZERO_WIDTH_JOINERS)
    text = drop_stray_nukta(text)
    text = unicodedata.normalize("NFKC", text)
    return text.translate(TELUGU_DIGITS).lower()


def has_content(text: str) -> bool:
    """True if the text contains at least one letter or number."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in text)


def normalize(tokens: list[Token]) -> list[Term]:
    terms = []
    for token in tokens:
        term = normalize_text(token.surface)
        if has_content(term):
            terms.append(Term(term, token))
    return terms


def analyze(text: str) -> list[Term]:
    """Full text-analysis chain shared by documents AND queries: tokenize -> normalize."""
    return normalize(tokenize(text))
