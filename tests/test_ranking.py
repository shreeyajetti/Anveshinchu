"""Tests for BM25 ranking, evaluation helpers, question terms and transliteration.  Run:  python -m unittest -v"""

import unittest

from src.evaluate import boolean_and, first_relevant_rank, ndcg, stem_index
from src.indexer import Document, build_index
from src.questions import question_terms
from src.ranking import BM25
from src.translit import transliterate

DOCS = [
    Document(0, "a#0", "గుంటూరు", "గుంటూరు జిల్లా గ్రామం"),
    Document(1, "b#0", "జిల్లా", "జిల్లా జిల్లా జిల్లా"),
    Document(2, "c#0", "గ్రామంలో", "గుంటూరు జిల్లాలో ఒక గ్రామంలో చెరువు ఉంది ఇక్కడ చాలా పొలాలు ఉన్నాయి"),
    Document(3, "d#0", "నది", "కృష్ణా నది"),
]


class TestBM25(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index(DOCS)
        cls.bm25 = BM25(cls.index)

    def test_rare_terms_weigh_more(self):
        # జిల్లా is in 2 of 4 passages, నది in 1: the rarer word is worth more.
        self.assertGreater(self.bm25.idf("నది"), self.bm25.idf("జిల్లా"))
        self.assertGreater(self.bm25.idf("జిల్లా"), 0)  # Lucene idf never goes negative

    def test_partial_matches_are_ranked(self):
        # Unlike AND, a passage containing only some query words still gets a score.
        ranked = [d for d, _ in self.bm25.top(["గుంటూరు", "నది"])]
        self.assertEqual(set(ranked), {0, 2, 3})
        self.assertEqual(boolean_and(self.index, ["గుంటూరు", "నది"]), set())

    def test_tf_saturates(self):
        jilla = self.bm25.scores(["జిల్లా"])  # passages 0 and 1 both have 4 terms
        self.assertGreater(jilla[1], jilla[0])  # tf 4 beats tf 1 ...
        self.assertLess(jilla[1], 2 * jilla[0])  # ... but is worth less than double, not 4x

    def test_long_passages_are_penalized(self):
        index = build_index([
            Document(0, "x#0", "నది", "కృష్ణా నది"),  # tf 2, 3 terms
            Document(1, "y#0", "నది", "నది ఒకటి రెండు మూడు నాలుగు ఐదు"),  # tf 2, 7 terms
        ])
        scores = BM25(index).scores(["నది"])
        self.assertGreater(scores[0], scores[1])

    def test_top_k_order_and_cutoff(self):
        top = self.bm25.top(["జిల్లా"], k=2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0][0], 1)  # 4 occurrences in a short passage
        self.assertGreaterEqual(top[0][1], top[1][1])

    def test_unknown_terms_score_nothing(self):
        self.assertEqual(self.bm25.top(["లేనిపదం"]), [])


class TestEvaluationHelpers(unittest.TestCase):
    def test_ndcg(self):
        self.assertEqual(ndcg([5, 1, 2], {5}), 1.0)  # relevant passage at rank 1
        self.assertAlmostEqual(ndcg([1, 5, 2], {5}), 1 / 1.584962500721156)  # rank 2: 1/log2(3)
        self.assertEqual(ndcg([1, 2], {5}), 0.0)

    def test_first_relevant_rank(self):
        self.assertEqual(first_relevant_rank([7, 3, 9], {9, 3}), 2)
        self.assertIsNone(first_relevant_rank([7], {3}))

    def test_stem_index_merges_postings_and_keeps_positions(self):
        index = build_index(DOCS)
        stemmed = stem_index(index, lambda t: t[:-2] if t.endswith("లో") else t)
        # గ్రామంలో (doc 2, positions 0 and 4) merges into గ్రామం (doc 0 position 3)
        self.assertEqual(stemmed.get_postings("గ్రామం"), {0: [3], 2: [0, 4]})
        self.assertEqual(index.get_postings("గ్రామం"), {0: [3]})  # original index untouched


class TestQuestionTerms(unittest.TestCase):
    def test_question_words_are_dropped(self):
        self.assertEqual(question_terms("హెమింగ్వే ఎప్పుడు పుట్టాడు?"), ["హెమింగ్వే", "పుట్టాడు"])
        self.assertEqual(question_terms("ఆ గ్రామ జనాభా ఎంత?"), ["ఆ", "గ్రామ", "జనాభా"])

    def test_fused_question_words_are_dropped(self):
        self.assertEqual(question_terms("పాల్ తండ్రి పేరేమిటి ?"), ["పాల్", "తండ్రి"])


class TestTransliteration(unittest.TestCase):
    def test_iso_15919(self):
        self.assertEqual(transliterate("రాష్ట్రం"), "rāṣṭraṁ")  # virama suppresses the inherent a
        self.assertEqual(transliterate("గ్రామంలో"), "grāmaṁlō")
        self.assertEqual(transliterate("ఇల్లు"), "illu")  # independent vowel
        self.assertEqual(transliterate("జన్మించారు"), "janmiṁcāru")

    def test_other_text_passes_through(self):
        self.assertEqual(transliterate("1919లో AND x"), "1919lō AND x")
        self.assertEqual(transliterate("౨౦౧౧"), "౨౦౧౧")  # Telugu digits kept
        self.assertEqual(transliterate("విక్రమ్\u200c"), "vikram")  # ZWNJ dropped


if __name__ == "__main__":
    unittest.main()
