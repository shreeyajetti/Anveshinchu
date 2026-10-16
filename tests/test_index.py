"""Unit tests on a tiny synthetic Telugu collection.  Run:  python -m unittest -v"""

import re
import tempfile
import unittest

from src.indexer import Document, build_index
from src.normalizer import analyze
from src.query import Phrase, QueryError, parse_query
from src.search import search, snippet
from src.storage import load_index, save_index
from src.tokenizer import tokenize

ZWNJ = "\u200c"

# Indexed text is "title\ntext". Positions per document:
# 0: రాముడు(0) | రాముడు(1) అడవికి(2) వెళ్ళాడు(3) రాముడు(4) ఇంటికి(5) తిరిగి(6) వచ్చాడు(7)
# 1: సీత(0) | సీత(1) ఇంట్లో(2) ఉంది(3) రాముడు(4) అడవిలో(5) ఉన్నాడు(6)
# 2: సారాభాయ్(0) | విక్రమ్(1) సారాభాయ్(2) 1919లో(3) జన్మించారు(4) జనాభా(5) 2011(6) గణన(7)
DOCS = [
    Document(0, "1#0", "రాముడు", "రాముడు అడవికి వెళ్ళాడు. రాముడు ఇంటికి తిరిగి వచ్చాడు."),
    Document(1, "2#0", "సీత", "సీత ఇంట్లో ఉంది. రాముడు అడవిలో ఉన్నాడు."),
    Document(2, "3#0", "సారాభాయ్", f"విక్రమ్{ZWNJ} సారాభాయ్ 1919లో జన్మించారు. జనాభా ౨౦౧౧ గణన."),
]


def doc_ids(index, query):
    return sorted(r.doc_id for r in search(index, query))


class TestPipeline(unittest.TestCase):
    def test_tokenizer_keeps_vowel_signs_and_drops_punctuation(self):
        self.assertEqual([t.surface for t in tokenize("కేంద్రం, 500 కి.మీ.")], ["కేంద్రం", "500", "కి", "మీ"])

    def test_regex_word_class_would_shred_telugu(self):
        # Documents why the tokenizer does not use \w: vowel signs are not "word characters".
        self.assertNotEqual(re.findall(r"\w+", "కేంద్రం"), ["కేంద్రం"])

    def test_tokenizer_offsets(self):
        [first, second] = tokenize("రాముడు అడవికి")
        self.assertEqual((first.start, first.end, second.start, second.end), (0, 6, 7, 13))

    def test_normalizer(self):
        self.assertEqual(analyze(f"విక్రమ్{ZWNJ}")[0].term, "విక్రమ్")  # zero-width joiner removed
        self.assertEqual(analyze("౨౦౧౧")[0].term, "2011")  # Telugu digits -> ASCII
        self.assertEqual(analyze("ＡＢＣ")[0].term, "abc")  # full-width -> ASCII, lowercased
        self.assertEqual(analyze("“ ” … ।"), [])  # punctuation only
        self.assertEqual(analyze("\u093cకేశవ")[0].term, "కేశవ")  # stray Devanagari nukta removed
        self.assertEqual(analyze("जड़ता")[0].term, "जड़ता")  # real Hindi nukta kept


class TestIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DOCS)

    def test_all_positions_are_stored(self):
        self.assertEqual(self.index.get_postings("రాముడు"), {0: [0, 1, 4], 1: [4]})

    def test_boolean(self):
        self.assertEqual(doc_ids(self.index, "రాముడు AND సీత"), [1])
        self.assertEqual(doc_ids(self.index, "రాముడు OR సారాభాయ్"), [0, 1, 2])
        self.assertEqual(doc_ids(self.index, "NOT రాముడు"), [2])
        self.assertEqual(doc_ids(self.index, "రాముడు AND NOT ఇంటికి"), [1])
        self.assertEqual(doc_ids(self.index, "(సీత OR సారాభాయ్) AND జనాభా"), [2])

    def test_phrase_requires_adjacency_and_order(self):
        self.assertEqual(doc_ids(self.index, '"రాముడు అడవికి"'), [0])
        self.assertEqual(doc_ids(self.index, '"అడవికి రాముడు"'), [])
        self.assertEqual(doc_ids(self.index, '"రాముడు ఇంటికి"'), [0])

    def test_phrase_ignores_punctuation_between_words(self):
        # "...వెళ్ళాడు. రాముడు..." : the full stop does not occupy a position
        self.assertEqual(doc_ids(self.index, '"వెళ్ళాడు రాముడు"'), [0])

    def test_query_goes_through_same_normalization(self):
        self.assertEqual(doc_ids(self.index, "విక్రమ్"), [2])
        self.assertEqual(doc_ids(self.index, f"విక్రమ్{ZWNJ}"), [2])
        self.assertEqual(doc_ids(self.index, "2011"), [2])
        self.assertEqual(doc_ids(self.index, "౨౦౧౧"), [2])

    def test_proximity_distance_and_order(self):
        # doc 1: ఇంట్లో=2, రాముడు=4 (distance 2)
        self.assertEqual(doc_ids(self.index, "ఇంట్లో /2 రాముడు"), [1])
        self.assertEqual(doc_ids(self.index, "రాముడు /2 ఇంట్లో"), [1])
        self.assertEqual(doc_ids(self.index, "ఇంట్లో /1 రాముడు"), [])

    def test_proximity_term_with_itself(self):
        self.assertEqual(doc_ids(self.index, "రాముడు /1 రాముడు"), [0])  # positions 0 and 1

    def test_match_positions_and_snippet(self):
        [result] = search(self.index, '"తిరిగి వచ్చాడు"')
        self.assertEqual(result.matches, [(6, 7)])
        self.assertIn("【తిరిగి వచ్చాడు】", snippet(self.index, 0, result.matches[0]))

    def test_unquoted_word_with_punctuation_is_a_phrase(self):
        self.assertEqual(parse_query("కి.మీ"), Phrase(("కి", "మీ")))

    def test_query_errors(self):
        for bad in ["", "రాముడు AND", "(రాముడు", "।", "రాముడు /2"]:
            with self.assertRaises(QueryError, msg=bad):
                parse_query(bad)

    @unittest.expectedFailure
    def test_known_gap_suffixed_forms(self):
        # ఇల్లు (house) should also find ఇంటికి (to the house) and ఇంట్లో (in the house).
        # Exact-form matching cannot do this yet; see the README roadmap.
        docs = [Document(0, "x#0", "ఇల్లు", "ఇల్లు")] + [Document(i + 1, d.docid, d.title, d.text) for i, d in enumerate(DOCS[:2])]
        self.assertEqual(doc_ids(build_index(docs), "ఇల్లు"), [0, 1, 2])


class TestStorage(unittest.TestCase):
    def test_round_trip(self):
        index = build_index(DOCS)
        with tempfile.TemporaryDirectory() as tmp:
            save_index(index, tmp)
            loaded = load_index(tmp)
        self.assertEqual(loaded.postings, index.postings)
        self.assertEqual(loaded.docs, index.docs)
        self.assertEqual(loaded.store, index.store)
        self.assertEqual(doc_ids(loaded, '"రాముడు అడవికి"'), [0])


if __name__ == "__main__":
    unittest.main()
