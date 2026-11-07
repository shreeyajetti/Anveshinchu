"""Command-line interface.

    python -m src.cli build    [--source wiki|miracl] [--index index]   # Storage
    python -m src.cli stats    [--index index] [--term T ...]          # Retrieval (load + inspect)
    python -m src.cli rare     [--count 10]                            # rare terms with their postings
    python -m src.cli search   "QUERY" [--index index]         # Search
    python -m src.cli search                                   # interactive search prompt
    python -m src.cli tokenize "తెలుగు వాక్యం"                   # show the analysis pipeline

Add --translit to any command to print Telugu in Latin letters (ISO 15919),
for terminals that render Telugu script incorrectly.
"""

import argparse
import random
import sys
import time
from pathlib import Path

from .indexer import load_documents
from .normalizer import analyze, normalize
from .query import QueryError
from .search import search, snippet
from .storage import build_disk_index, load_index
from .tokenizer import tokenize
from .translit import TransliteratingStream


DEFAULT_DUMP = ".cache/tewiki/tewiki-20261101-pages-articles.xml.bz2"
PIPELINE_META = {
    "language": "Telugu",
    "tokenizer": "Unicode letter/mark/number runs",
    "normalization": "remove ZWNJ/ZWJ and stray nukta, NFKC, Telugu digits -> ASCII, lowercase",
}


def cmd_build(args) -> None:
    started = time.perf_counter()
    if args.source == "wiki":
        from .wikidump import iter_articles

        documents = iter_articles(args.dump)
        meta = {**PIPELINE_META, "collection": "Telugu Wikipedia, all articles", "source": Path(args.dump).name}
        print(f"Streaming articles from {args.dump}")
    else:
        documents = load_documents(args.data)
        meta = {**PIPELINE_META, "collection": "MIRACL v1.0 Telugu (subset)", "source": "data/passages.jsonl"}
        print(f"Loaded {len(documents):,} passages from {args.data}/")

    def progress(writer):
        print(f"  {writer.num_docs:,} documents, {writer.num_positions:,} positions, "
              f"{len(writer.blocks)} blocks written, {time.perf_counter() - started:.0f}s", flush=True)

    m = build_disk_index(documents, args.index, meta, args.block_positions, progress)
    print(
        f"Indexed {m['num_docs']:,} docs, {m['num_terms']:,} distinct terms, "
        f"{m['num_postings']:,} postings, {m['num_positions']:,} positions "
        f"in {time.perf_counter() - started:.2f}s ({m['num_blocks']} blocks merged in {m['merge_seconds']}s)"
    )
    print(f"Saved index to {Path(args.index).as_posix()}/")


def print_postings(index, term: str, limit: int) -> None:
    postings = index.get_postings(term)
    print(f"\nTerm {term!r}: document frequency (df) {index.df(term):,}, collection frequency (cf) {index.cf(term):,}")
    for doc_id, positions in sorted(postings.items())[:limit]:
        info = index.docs[doc_id]
        print(f"  doc {doc_id} [{info['docid']}] {info['title']}: tf={len(positions)} positions={positions}")
    if len(postings) > limit:
        print(f"  ... {len(postings) - limit:,} more documents")


def cmd_stats(args) -> None:
    started = time.perf_counter()
    index = load_index(args.index)
    print(f"Loaded vocabulary ({len(index.vocabulary):,} terms) and document table from {args.index}/ "
          f"in {time.perf_counter() - started:.1f}s; postings stay on disk")
    for key, value in index.meta.items():
        print(f"  {key}: {value}")
    for term in args.term or []:
        analyzed = [t.term for t in analyze(term)]  # same normalization as the documents
        print_postings(index, analyzed[0] if len(analyzed) == 1 else term, args.limit)


def is_telugu_word(term: str) -> bool:
    return all("\u0c00" <= ch <= "\u0c7f" for ch in term)


def cmd_rare(args) -> None:
    """Pick rare terms (low df) at random, with a fixed seed, and print their positional postings."""
    index = load_index(args.index)
    v = index.vocabulary
    candidates = [
        i for i in range(len(v))
        if v.df[i] <= args.max_df and v.cf[i] >= args.min_cf and len(v.terms[i]) >= args.min_length
        and is_telugu_word(v.terms[i])
    ]
    print(f"{len(candidates):,} candidate terms: Telugu script only, at least {args.min_length} code points, "
          f"df <= {args.max_df}, cf >= {args.min_cf}; {args.count} chosen at random (seed {args.seed})")
    for i in sorted(random.Random(args.seed).sample(candidates, args.count), key=lambda i: v.terms[i]):
        print_postings(index, v.terms[i], args.limit)


def print_results(index, query: str, max_snippets: int, top: int) -> None:
    try:
        results = search(index, query)
    except QueryError as e:
        print(f"Query error: {e}")
        return
    print(f"Query: {query}  ->  {len(results):,} document(s)")
    for r in results[:top]:
        print(f"  doc {r.doc_id} [{r.docid}] {r.title}  ({len(r.matches)} match(es))")
        for match in r.matches[:max_snippets]:
            print(f"      positions {match[0]}-{match[1]}: {snippet(index, r.doc_id, match)}")
        if len(r.matches) > max_snippets:
            print(f"      ... {len(r.matches) - max_snippets} more")
    if len(results) > top:
        print(f"  ... {len(results) - top:,} more documents (use --top to show more)")


def cmd_search(args) -> None:
    index = load_index(args.index)
    if args.query:
        print_results(index, args.query, args.snippets, args.top)
        return
    print("Interactive search. Examples: గుంటూరు AND జిల్లా | \"తెలుగు సినిమా\" | సినిమా /3 దర్శకత్వం | empty line to quit")
    while True:
        try:
            query = input("query> ").strip()
        except EOFError:
            break
        if not query:
            break
        print_results(index, query, args.snippets, args.top)


def visible(text: str) -> str:
    """Show invisible zero-width joiners explicitly, e.g. విక్రమ్<ZWNJ>."""
    return text.replace("\u200c", "<ZWNJ>").replace("\u200d", "<ZWJ>")


def cmd_tokenize(args) -> None:
    tokens = tokenize(args.text)
    print(f"Input: {visible(args.text)}")
    print("\n1. Tokenizer (runs of Unicode letters, vowel signs/marks, numbers):")
    print("   " + " | ".join(visible(t.surface) for t in tokens))
    for t in tokens:
        codepoints = " ".join(f"{ord(ch):04X}" for ch in t.surface)
        print(f"   {t.start:>3}-{t.end:<3} {visible(t.surface)}   [{codepoints}]")
    terms = normalize(tokens)
    print("\n2. Normalizer (remove ZWNJ/ZWJ, NFKC, Telugu digits -> 0-9, lowercase) -> index terms with positions:")
    print("   " + "  ".join(f"{i}:{t.term}" for i, t in enumerate(terms)))


def main(argv=None) -> None:
    # Windows consoles default to cp1252, which cannot print Telugu.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Anveshinchu: positional inverted index search engine")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--translit", action="store_true", help="print Telugu in Latin letters (ISO 15919)")

    p = sub.add_parser("build", parents=[common], help="build the disk index (vocabulary + postings) in index/")
    p.add_argument("--source", choices=["wiki", "miracl"], default="wiki",
                   help="wiki: the Telugu Wikipedia XML dump (default); miracl: data/passages.jsonl, for evaluation")
    p.add_argument("--dump", default=DEFAULT_DUMP, help="path of the tewiki-*-pages-articles.xml.bz2 dump")
    p.add_argument("--data", default="data")
    p.add_argument("--index", default="index")
    p.add_argument("--block-positions", type=int, default=2_000_000, help="positions per in-memory block")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("stats", parents=[common], help="load a saved index and print statistics / postings")
    p.add_argument("--index", default="index")
    p.add_argument("--term", nargs="*", help="show the positional postings list of these terms")
    p.add_argument("--limit", type=int, default=10, help="max documents shown per postings list")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("rare", parents=[common], help="print randomly chosen rare terms with df, cf and postings")
    p.add_argument("--index", default="index")
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--max-df", type=int, default=3)
    p.add_argument("--min-cf", type=int, default=2)
    p.add_argument("--min-length", type=int, default=5)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--limit", type=int, default=10, help="max documents shown per postings list")
    p.set_defaults(func=cmd_rare)

    p = sub.add_parser("search", parents=[common], help="run a query against a saved index")
    p.add_argument("query", nargs="?", help="omit for an interactive prompt")
    p.add_argument("--index", default="index")
    p.add_argument("--snippets", type=int, default=2, help="max snippets shown per document")
    p.add_argument("--top", type=int, default=10, help="max documents shown")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("tokenize", parents=[common], help="show tokenizer and normalizer output for a sentence")
    p.add_argument("text")
    p.set_defaults(func=cmd_tokenize)

    args = parser.parse_args(argv)
    if args.translit:
        sys.stdout = TransliteratingStream(sys.stdout)
    try:
        args.func(args)
    finally:
        if isinstance(sys.stdout, TransliteratingStream):
            sys.stdout = sys.stdout.stream


if __name__ == "__main__":
    main()
