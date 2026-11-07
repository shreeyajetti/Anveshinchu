"""Tests for the disk index (SPIMI blocks, merge, vocabulary, seek-based postings) and the dump reader.

Run:  python -m unittest -v
"""

import bz2
import tempfile
import unittest
from pathlib import Path

from src.indexer import Document, build_index
from src.search import search
from src.storage import build_disk_index, format_postings, load_index, parse_postings
from src.wikidump import clean_wikitext, iter_articles

DOCS = [
    Document(0, "1", "రాముడు", "రాముడు అడవికి వెళ్ళాడు రాముడు ఇంటికి తిరిగి వచ్చాడు"),
    Document(1, "2", "సీత", "సీత ఇంట్లో ఉంది రాముడు అడవిలో ఉన్నాడు"),
    Document(2, "3", "సారాభాయ్", "విక్రమ్ సారాభాయ్ 1919లో జన్మించారు"),
    Document(3, "4", "అడవి", "అడవి అడవి రాముడు"),
]


class TestDiskIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # A tiny block size forces one block per document, so the k-way merge is exercised.
        cls.meta = build_disk_index(DOCS, cls.tmp.name, {"collection": "test"}, block_positions=1)
        cls.disk = load_index(cls.tmp.name)
        cls.memory = build_index(DOCS)

    @classmethod
    def tearDownClass(cls):
        cls.disk.close()
        cls.tmp.cleanup()

    def test_blocks_were_merged(self):
        self.assertEqual(self.meta["num_blocks"], 4)
        self.assertFalse((Path(self.tmp.name) / "blocks").exists())  # deleted after the merge

    def test_same_postings_as_in_memory_index(self):
        self.assertEqual(len(self.disk.vocabulary), len(self.memory.postings))
        for term, postings in self.memory.postings.items():
            self.assertEqual(self.disk.get_postings(term), postings, term)
        self.assertEqual(dict(self.disk.iter_postings()), self.memory.postings)

    def test_df_and_cf(self):
        # రాముడు: doc 0 at 0, 1, 4; doc 1 at 4; doc 3 at 3  ->  df 3, cf 5
        self.assertEqual(self.disk.get_postings("రాముడు"), {0: [0, 1, 4], 1: [4], 3: [3]})
        self.assertEqual((self.disk.df("రాముడు"), self.disk.cf("రాముడు")), (3, 5))
        self.assertEqual((self.memory.df("రాముడు"), self.memory.cf("రాముడు")), (3, 5))
        self.assertEqual((self.disk.df("అడవి"), self.disk.cf("అడవి")), (1, 3))  # title + 2 in text
        self.assertEqual((self.disk.df("లేదు"), self.disk.cf("లేదు")), (0, 0))

    def test_vocabulary_is_sorted_and_points_into_postings_file(self):
        v = self.disk.vocabulary
        self.assertEqual(v.terms, sorted(v.terms))
        raw = (Path(self.tmp.name) / "postings.txt").read_bytes()
        i = v.find("సీత")
        line = raw[v.offset[i]: v.offset[i] + v.length[i]].decode("utf-8")
        self.assertEqual(line, "సీత\t1:0,1\n")

    def test_documents_and_store(self):
        self.assertEqual(self.disk.docs[2], {"docid": "3", "title": "సారాభాయ్", "num_terms": 5})
        self.assertEqual(self.disk.store.get(1), DOCS[1].indexed_text)
        self.assertIsNone(self.disk.store.get(99))

    def test_search_works_on_disk_index(self):
        self.assertEqual([r.doc_id for r in search(self.disk, '"రాముడు అడవికి"')], [0])
        self.assertEqual(sorted(r.doc_id for r in search(self.disk, "రాముడు AND NOT అడవి")), [0, 1])

    def test_postings_format_round_trip(self):
        postings = {12: [0, 3, 151], 40: [88]}
        self.assertEqual(format_postings(postings), "12:0,3,151;40:88")
        self.assertEqual(parse_postings("12:0,3,151;40:88"), postings)


class TestWikiDump(unittest.TestCase):
    def test_clean_wikitext(self):
        raw = (
            "'''గుంటూరు''' [[ఆంధ్ర ప్రదేశ్]] లోని ఒక [[నగరం|నగరము]].<ref>మూలం</ref>\n"
            "{{Infobox {{nested}} x}}\n<!-- comment -->\n"
            "[[దస్త్రం:Guntur.jpg|thumb|[[గుంటూరు]] చిత్రం]]\n"
            "== చరిత్ర ==\n* [https://example.org వెబ్] &amp; చరిత్ర\n"
            "{| class=wikitable\n|-\n| cell\n|}\n[[వర్గం:నగరాలు]]"
        )
        self.assertEqual(
            clean_wikitext(raw, frozenset({"దస్త్రం", "వర్గం"})),
            "గుంటూరు ఆంధ్ర ప్రదేశ్ లోని ఒక నగరము.\nచరిత్ర\nవెబ్ & చరిత్ర",
        )

    def test_iter_articles_skips_redirects_and_other_namespaces(self):
        xml = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <siteinfo><namespaces><namespace key="6">దస్త్రం</namespace><namespace key="14">వర్గం</namespace></namespaces></siteinfo>
  <page><title>గుంటూరు</title><ns>0</ns><id>786</id><revision><text>'''గుంటూరు''' ఒక నగరం. [[వర్గం:నగరాలు]]</text></revision></page>
  <page><title>Guntur</title><ns>0</ns><id>787</id><redirect title="గుంటూరు" /><revision><text>#REDIRECT [[గుంటూరు]]</text></revision></page>
  <page><title>వర్గం:నగరాలు</title><ns>14</ns><id>788</id><revision><text>నగరాలు</text></revision></page>
  <page><title>సీత</title><ns>0</ns><id>789</id><revision><text>సీత</text></revision></page>
</mediawiki>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dump.xml.bz2"
            path.write_bytes(bz2.compress(xml.encode("utf-8")))
            docs = list(iter_articles(path))
        self.assertEqual([(d.doc_id, d.docid, d.title, d.text) for d in docs],
                         [(0, "786", "గుంటూరు", "గుంటూరు ఒక నగరం."), (1, "789", "సీత", "సీత")])


if __name__ == "__main__":
    unittest.main()
