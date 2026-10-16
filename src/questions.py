"""Turning a natural-language question into query terms.

Question words like ఎప్పుడు ("when") or ఎంత ("how much") are essential to the
question but never appear in the passage that answers it, so they are
dropped from questions before searching. They stay in the index, because
phrase queries need every word's position.

The list was built from the 828 MIRACL dev questions and checked by a native
speaker; it includes case forms (ఎవరికి, ఎక్కడి) that the dev questions
happen not to use. Some questions fuse a content word with a question word
in one token (పేరేమిటి = పేరు "name" + ఏమిటి "what"); these are dropped too
for now, which loses the content word.
"""

from .normalizer import analyze

QUESTION_WORDS = frozenset(
    """
    ఎంత ఎంతమంది ఎప్పుడు ఎపుడు ఏ ఏం ఏది ఏమిటి ఏంటి ఏమని ఏమంటారు ఎవరు ఎవరి ఎవరికి ఎవరికీ ఎవడే
    ఎక్కడ ఎక్కడి ఎన్ని ఎన్నో ఎందుకు ఎలా
    """.split()
)

FUSED_QUESTION_WORDS = frozenset("పేరేమిటి పేర్లేమిటి పేరేంటి తల్లిదండ్రులెవరు".split())


def question_terms(question: str) -> list[str]:
    """Index terms of a question, without question words, in order of appearance."""
    return [
        t.term
        for t in analyze(question)
        if t.term not in QUESTION_WORDS and t.term not in FUSED_QUESTION_WORDS
    ]
