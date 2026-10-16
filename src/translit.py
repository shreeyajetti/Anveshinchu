"""Telugu -> Latin transliteration (ISO 15919), for terminals that can't render Telugu.

Many terminals (e.g. the Windows console) break Telugu conjuncts like ష్ట్ర
apart, so raw output can't be trusted visually. ISO 15919 is the standard
scholarly romanization of Indic scripts:

    రాష్ట్రం -> rāṣṭraṁ      గ్రామంలో -> grāmaṁlō      హెమింగ్<ZWNJ>వే -> hemiṁgvē

A consonant carries an inherent "a" unless a vowel sign or the virama (్)
follows it. Everything else passes through unchanged, including Telugu
digits (౨౦౧౧), which render fine and which the tokenize demo needs to show
before normalization.
"""

INDEPENDENT_VOWELS = dict(zip("అఆఇఈఉఊఋౠఌఎఏఐఒఓఔ", "a ā i ī u ū r̥ r̥̄ l̥ e ē ai o ō au".split()))
VOWEL_SIGNS = dict(zip("ాిీుూృౄెేైొోౌ", "ā i ī u ū r̥ r̥̄ e ē ai o ō au".split()))
CONSONANTS = dict(
    zip(
        "కఖగఘఙచఛజఝఞటఠడఢణతథదధనపఫబభమయరఱలళఴవశషసహ",
        "k kh g gh ṅ c ch j jh ñ ṭ ṭh ḍ ḍh ṇ t th d dh n p ph b bh m y r ṟ l ḷ ḻ v ś ṣ s h".split(),
    )
)
VIRAMA = "్"
OTHER = {"ం": "ṁ", "ః": "ḥ", "ఁ": "m̐", "\u200c": "", "\u200d": ""}


def transliterate(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch in CONSONANTS:
            nxt = text[i + 1] if i + 1 < len(text) else ""
            out.append(CONSONANTS[ch] + ("" if nxt in VOWEL_SIGNS or nxt == VIRAMA else "a"))
        elif ch in VOWEL_SIGNS:
            out.append(VOWEL_SIGNS[ch])
        elif ch == VIRAMA:
            pass  # suppresses the inherent "a" of the consonant before it
        elif ch in INDEPENDENT_VOWELS:
            out.append(INDEPENDENT_VOWELS[ch])
        else:
            out.append(OTHER.get(ch, ch))
    return "".join(out)


class TransliteratingStream:
    """Wraps a text stream so everything printed to it is transliterated."""

    def __init__(self, stream):
        self.stream = stream

    def write(self, text: str) -> int:
        return self.stream.write(transliterate(text))

    def __getattr__(self, name):
        return getattr(self.stream, name)
