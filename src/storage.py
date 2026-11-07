"""Storage and retrieval: a disk-based positional index.

The vocabulary is kept in main memory; the postings lists stay on secondary
storage (disk) and are read one term at a time with a file seek.

Building (single-pass in-memory indexing, SPIMI)
-------------------------------------------------
The whole Telugu Wikipedia does not fit in memory as Python postings lists,
so documents are indexed in blocks:

1. Documents are analyzed and added to an in-memory block index until it
   holds about `block_positions` positions (2 million by default).
2. The block is written to disk sorted by term (index/blocks/block_0000.tsv),
   and memory is freed for the next block.
3. When all documents are done, the sorted blocks are merged in one pass
   (a k-way merge with heapq.merge). Doc IDs increase from block to block, so
   a term's merged postings are just its block postings joined in order.
4. The merge writes postings.txt and, for every term, one vocabulary entry:
   document frequency, collection frequency, and where its postings line
   starts in postings.txt (byte offset + length). The blocks are deleted.

Files in the index directory (all UTF-8 text, so every file can be opened
and read; Telugu is stored as-is, not as \\u escapes):

- vocabulary.tsv  term, df, cf, offset, length       (loaded into memory)
- postings.txt    term TAB doc:pos,pos;doc:pos ...   (stays on disk)
- docs.tsv        doc_id, source ID, number of terms, text offset, text length, title
- store.jsonl     the indexed text of each document, for snippets (stays on disk)
- meta.json       collection description and statistics

Example lines (Telugu Wikipedia):

    vocabulary.tsv:  గుంటూరు  1873  6904  80213350  41022
    postings.txt:    గుంటూరు  12:0,3,151;40:88;...

df = number of documents containing the term (length of its postings list),
cf = total occurrences in the collection (sum of all its positions).
"""

import heapq
import json
import shutil
import time
from array import array
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from pathlib import Path

from .indexer import Document, index_document

VOCAB_FILE = "vocabulary.tsv"
POSTINGS_FILE = "postings.txt"
DOCS_FILE = "docs.tsv"
STORE_FILE = "store.jsonl"
META_FILE = "meta.json"
BLOCK_DIR = "blocks"


def format_postings(docs: dict[int, list[int]]) -> str:
    """{12: [0, 3], 40: [88]} -> "12:0,3;40:88" (doc IDs ascending)."""
    return ";".join(f"{d}:{','.join(map(str, positions))}" for d, positions in sorted(docs.items()))


def parse_postings(text: str) -> dict[int, list[int]]:
    postings = {}
    for entry in text.split(";"):
        d, positions = entry.split(":")
        postings[int(d)] = [int(p) for p in positions.split(",")]
    return postings


def _clean_field(text: str) -> str:
    return text.replace("\t", " ").replace("\n", " ")


# ----------------------------------------------------------------------------- building


class IndexWriter:
    """Builds the disk index block by block (SPIMI). Use add() for each document, then close()."""

    def __init__(self, index_dir: str | Path, block_positions: int = 2_000_000):
        self.dir = Path(index_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.block_dir = self.dir / BLOCK_DIR
        shutil.rmtree(self.block_dir, ignore_errors=True)
        self.block_dir.mkdir()
        self.block_positions = block_positions
        self.blocks: list[Path] = []
        self.postings: dict[str, dict[int, list[int]]] = {}
        self.block_size = 0
        self.num_docs = self.num_positions = 0
        self.docs_out = open(self.dir / DOCS_FILE, "w", encoding="utf-8", newline="\n")
        self.store_out = open(self.dir / STORE_FILE, "wb")

    def add(self, doc: Document) -> None:
        text = doc.indexed_text
        num_terms = index_document(self.postings, doc.doc_id, text)
        encoded = (json.dumps(text, ensure_ascii=False) + "\n").encode("utf-8")
        offset = self.store_out.tell()
        self.store_out.write(encoded)
        self.docs_out.write(
            f"{doc.doc_id}\t{doc.docid}\t{num_terms}\t{offset}\t{len(encoded)}\t{_clean_field(doc.title)}\n"
        )
        self.num_docs += 1
        self.num_positions += num_terms
        self.block_size += num_terms
        if self.block_size >= self.block_positions:
            self.flush_block()

    def flush_block(self) -> None:
        """Write the in-memory block to disk, sorted by term: term TAB df TAB cf TAB postings."""
        if not self.postings:
            return
        path = self.block_dir / f"block_{len(self.blocks):04d}.tsv"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for term in sorted(self.postings):
                docs = self.postings[term]
                cf = sum(len(p) for p in docs.values())
                f.write(f"{term}\t{len(docs)}\t{cf}\t{format_postings(docs)}\n")
        self.blocks.append(path)
        self.postings = {}
        self.block_size = 0

    def close(self, meta: dict) -> dict:
        """Flush the last block, merge all blocks into postings.txt + vocabulary.tsv, write meta.json."""
        self.flush_block()
        self.docs_out.close()
        self.store_out.close()
        started = time.perf_counter()
        num_terms = num_postings = 0
        with open(self.dir / POSTINGS_FILE, "wb") as postings_out, \
                open(self.dir / VOCAB_FILE, "w", encoding="utf-8", newline="\n") as vocab_out:
            for term, df, cf, postings in merge_blocks(self.blocks):
                line = f"{term}\t{postings}\n".encode("utf-8")
                vocab_out.write(f"{term}\t{df}\t{cf}\t{postings_out.tell()}\t{len(line)}\n")
                postings_out.write(line)
                num_terms += 1
                num_postings += df
        merge_seconds = time.perf_counter() - started
        shutil.rmtree(self.block_dir)
        meta = {
            **meta,
            "num_docs": self.num_docs,
            "num_terms": num_terms,
            "num_postings": num_postings,
            "num_positions": self.num_positions,
            "num_blocks": len(self.blocks),
            "block_positions": self.block_positions,
            "merge_seconds": round(merge_seconds, 1),
        }
        (self.dir / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return meta


def _read_block(path: Path, block_no: int) -> Iterator[tuple[str, int, int, int, str]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            term, df, cf, postings = line.rstrip("\n").split("\t")
            yield term, block_no, int(df), int(cf), postings


def merge_blocks(blocks: list[Path]) -> Iterator[tuple[str, int, int, str]]:
    """k-way merge of sorted block files -> (term, df, cf, postings) in term order.

    Entries for the same term arrive in block order (ties are broken by block
    number), and block i only contains doc IDs smaller than block i+1, so
    joining the postings strings keeps doc IDs sorted.
    """
    current, df, cf, parts = None, 0, 0, []
    for term, _, block_df, block_cf, postings in heapq.merge(*(_read_block(p, i) for i, p in enumerate(blocks))):
        if term != current:
            if current is not None:
                yield current, df, cf, ";".join(parts)
            current, df, cf, parts = term, 0, 0, []
        df += block_df
        cf += block_cf
        parts.append(postings)
    if current is not None:
        yield current, df, cf, ";".join(parts)


def build_disk_index(
    documents: Iterable[Document], index_dir: str | Path, meta: dict | None = None, block_positions: int = 2_000_000,
    progress=None,
) -> dict:
    """Index documents into index_dir block by block; returns the statistics written to meta.json."""
    writer = IndexWriter(index_dir, block_positions)
    for doc in documents:
        writer.add(doc)
        if progress and writer.num_docs % 10_000 == 0:
            progress(writer)
    return writer.close(meta or {})


# ----------------------------------------------------------------------------- retrieval


class Vocabulary:
    """The in-memory vocabulary: term -> (df, cf, offset, length).

    Stored as one sorted list of terms plus four parallel integer arrays and
    looked up with binary search. That takes roughly a third of the memory of
    a dict of tuples, which matters with millions of Telugu terms.
    """

    def __init__(self, path: Path):
        self.terms: list[str] = []
        self.df, self.cf = array("l"), array("q")
        self.offset, self.length = array("q"), array("l")
        with open(path, encoding="utf-8") as f:
            for line in f:
                term, df, cf, offset, length = line.rstrip("\n").split("\t")
                self.terms.append(term)
                self.df.append(int(df))
                self.cf.append(int(cf))
                self.offset.append(int(offset))
                self.length.append(int(length))

    def find(self, term: str) -> int | None:
        i = bisect_left(self.terms, term)
        return i if i < len(self.terms) and self.terms[i] == term else None

    def __len__(self) -> int:
        return len(self.terms)

    def __contains__(self, term: str) -> bool:
        return self.find(term) is not None


class DocStore:
    """Document texts, read from store.jsonl on demand (used only for snippets)."""

    def __init__(self, path: Path, offsets: array, lengths: array):
        self.path, self.offsets, self.lengths = path, offsets, lengths

    def get(self, doc_id: int, default=None):
        if not 0 <= doc_id < len(self.offsets):
            return default
        with open(self.path, "rb") as f:
            f.seek(self.offsets[doc_id])
            return json.loads(f.read(self.lengths[doc_id]).decode("utf-8"))


class DiskIndex:
    """A loaded index: vocabulary and document table in memory, postings and texts on disk.

    It has the same interface as indexer.InvertedIndex (get_postings, docs,
    store, all_doc_ids), so search, ranking and evaluation work with either.
    """

    def __init__(self, index_dir: str | Path):
        self.dir = Path(index_dir)
        self.meta = json.loads((self.dir / META_FILE).read_text(encoding="utf-8"))
        self.vocabulary = Vocabulary(self.dir / VOCAB_FILE)
        self.docs: dict[int, dict] = {}
        offsets, lengths = array("q"), array("l")
        with open(self.dir / DOCS_FILE, encoding="utf-8") as f:
            for line in f:
                doc_id, docid, num_terms, offset, length, title = line.rstrip("\n").split("\t", 5)
                self.docs[int(doc_id)] = {"docid": docid, "title": title, "num_terms": int(num_terms)}
                offsets.append(int(offset))
                lengths.append(int(length))
        self.store = DocStore(self.dir / STORE_FILE, offsets, lengths)
        self._postings_file = open(self.dir / POSTINGS_FILE, "rb")

    def close(self) -> None:
        self._postings_file.close()

    def df(self, term: str) -> int:
        i = self.vocabulary.find(term)
        return 0 if i is None else self.vocabulary.df[i]

    def cf(self, term: str) -> int:
        i = self.vocabulary.find(term)
        return 0 if i is None else self.vocabulary.cf[i]

    def get_postings(self, term: str) -> dict[int, list[int]]:
        """Read one postings list from disk: seek to its offset, read exactly its bytes."""
        i = self.vocabulary.find(term)
        if i is None:
            return {}
        self._postings_file.seek(self.vocabulary.offset[i])
        line = self._postings_file.read(self.vocabulary.length[i]).decode("utf-8")
        stored_term, postings = line.rstrip("\n").split("\t", 1)
        assert stored_term == term, f"vocabulary offset for {term!r} points at {stored_term!r}"
        return parse_postings(postings)

    def iter_postings(self) -> Iterator[tuple[str, dict[int, list[int]]]]:
        """Every (term, postings) pair in term order, read sequentially from disk."""
        with open(self.dir / POSTINGS_FILE, encoding="utf-8") as f:
            for line in f:
                term, postings = line.rstrip("\n").split("\t", 1)
                yield term, parse_postings(postings)

    def all_doc_ids(self) -> set[int]:
        return set(self.docs)


def load_index(index_dir: str | Path) -> DiskIndex:
    """Load a previously built index: reads the vocabulary and document table, not the postings."""
    return DiskIndex(index_dir)
