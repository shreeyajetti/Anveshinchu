"""Command-line interface.

    python -m src.cli build    [--data data] [--index index]   # Storage
    python -m src.cli stats    [--index index]                 # Retrieval (load + inspect)
    python -m src.cli search   "QUERY" [--index index]         # Search
    python -m src.cli search                                   # interactive search prompt
    python -m src.cli tokenize "తెలుగు వాక్యం"                   # show the analysis pipeline

Add --translit to any command to print Telugu in Latin letters (ISO 15919),
for terminals that render Telugu script incorrectly.
"""

import argparse
import sys
import time

from .indexer import build_index, load_documents
from .normalizer import normalize
from .query import QueryError
from .search import search, snippet
from .storage import load_index, save_index
from .tokenizer import tokenize
from .translit import TransliteratingStream


def cmd_build(args) -> None:
    started = time.perf_counter()
    documents = load_documents(args.data)
    articles = {d.docid.split("#")[0] for d in documents}
    print(f"Loaded {len(documents):,} passages from {len(articles):,} articles in {args.data}/")
    index = build_index(documents)
    path = save_index(index, args.index)
    m = index.meta
    print(
        f"Indexed {m['num_docs']:,} docs, {m['num_terms']:,} distinct terms, "
        f"{m['num_postings']:,} postings, {m['num_positions']:,} positions "
        f"in {time.perf_counter() - started:.2f}s"
    )
    print(f"Saved index to {path.as_posix()}")


def cmd_stats(args) -> None:
    started = time.perf_counter()
    index = load_index(args.index)
    print(f"Loaded index from {args.index}/ in {time.perf_counter() - started:.3f}s (no re-tokenization)")
    for key, value in index.meta.items():
        print(f"  {key}: {value}")
    if args.term:
        for term in args.term:
            postings = index.get_postings(term)
            print(f"\nPostings for {term!r} (document frequency {len(postings):,}):")
            for doc_id, positions in sorted(postings.items())[: args.limit]:
                info = index.docs[doc_id]
                print(f"  doc {doc_id} [{info['docid']}] {info['title']}: tf={len(positions)} positions={positions}")
            if len(postings) > args.limit:
                print(f"  ... {len(postings) - args.limit:,} more documents")


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

    p = sub.add_parser("build", parents=[common], help="build the index from data/ and save it to index/")
    p.add_argument("--data", default="data")
    p.add_argument("--index", default="index")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("stats", parents=[common], help="load a saved index and print statistics / postings")
    p.add_argument("--index", default="index")
    p.add_argument("--term", nargs="*", help="show the positional postings list of these terms")
    p.add_argument("--limit", type=int, default=10, help="max documents shown per postings list")
    p.set_defaults(func=cmd_stats)

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
