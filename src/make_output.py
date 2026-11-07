"""Generate output.txt: 10 rare terms with their positional index, and 5 test cases.

    python -m src.make_output [--index index] [--out output.txt]

Every command shown is run for real against the built index, and each test
case checks its result independently against the postings lists read from
disk, printing PASS or FAIL.
"""

import argparse
import contextlib
import io
import sys
from pathlib import Path

from . import cli
from .normalizer import analyze
from .search import search
from .storage import POSTINGS_FILE, load_index


def run_cli(*argv: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(list(argv))
    return buf.getvalue().rstrip()


def check(lines: list[str], condition: bool, description: str) -> bool:
    lines.append(f"  [{'PASS' if condition else 'FAIL'}] {description}")
    return condition


def section(title: str) -> list[str]:
    return ["", "=" * 100, title, "=" * 100]


def test_storage(index, out: list[str]) -> bool:
    term = "గుంటూరు"
    out += section("TEST CASE 1: Storage and retrieval - vocabulary in memory, postings read from disk by seek")
    v = index.vocabulary
    i = v.find(term)
    out.append(f"Vocabulary entry (in memory) for {term}: df={v.df[i]:,} cf={v.cf[i]:,} "
               f"offset={v.offset[i]:,} length={v.length[i]:,} bytes")
    with open(Path(index.dir) / POSTINGS_FILE, "rb") as f:
        f.seek(v.offset[i])
        raw = f.read(v.length[i]).decode("utf-8")
    out.append(f"Bytes {v.offset[i]:,}..{v.offset[i] + v.length[i]:,} of {POSTINGS_FILE} (first 300 characters):")
    out.append("  " + raw[:300] + " ...")
    postings = index.get_postings(term)
    ok = check(out, raw.startswith(term + "\t"), "the vocabulary offset points exactly at this term's postings line")
    ok &= check(out, len(postings) == v.df[i], f"df = number of documents in the postings list ({len(postings):,})")
    ok &= check(out, sum(map(len, postings.values())) == v.cf[i],
                f"cf = total number of positions in the postings list ({sum(map(len, postings.values())):,})")
    ok &= check(out, all(p == sorted(p) for p in postings.values()), "every position list is sorted")
    return ok


def test_tokenizer(out: list[str]) -> bool:
    text = "విక్రమ్\u200c సారాభాయ్, 500 కి.మీ. (౨౦౧౧)"
    out += section("TEST CASE 2: Tokenizer and normalizer - ZWNJ, punctuation, Telugu digits")
    out.append("$ python -m src.cli tokenize \"విక్రమ్<ZWNJ> సారాభాయ్, 500 కి.మీ. (౨౦౧౧)\"")
    out.append(run_cli("tokenize", text))
    expected = ["విక్రమ్", "సారాభాయ్", "500", "కి", "మీ", "2011"]
    got = [t.term for t in analyze(text)]
    return check(out, got == expected, f"index terms are {expected} (ZWNJ removed, punctuation split off, ౨౦౧౧ -> 2011)")


def test_boolean(index, out: list[str]) -> bool:
    query = "గుంటూరు AND జిల్లా AND NOT ప్రకాశం"
    out += section("TEST CASE 3: Boolean query (AND, NOT)")
    out.append(f"$ python -m src.cli search \"{query}\" --top 5 --snippets 1")
    out.append(run_cli("search", query, "--index", str(index.dir), "--top", "5", "--snippets", "1"))
    a, b, c = (set(index.get_postings(t)) for t in ("గుంటూరు", "జిల్లా", "ప్రకాశం"))
    expected = (a & b) - c
    got = {r.doc_id for r in search(index, query)}
    out.append(f"Check from postings: |గుంటూరు| = {len(a):,}, |జిల్లా| = {len(b):,}, |ప్రకాశం| = {len(c):,}, "
               f"(గుంటూరు ∩ జిల్లా) − ప్రకాశం = {len(expected):,}")
    return check(out, got == expected, "the result set equals the set operations on the postings lists")


def test_phrase(index, out: list[str]) -> bool:
    query = '"తెలుగు సినిమా"'
    out += section("TEST CASE 4: Phrase query - terms must be adjacent and in order")
    out.append(f"$ python -m src.cli search '{query}' --top 5 --snippets 1")
    out.append(run_cli("search", query, "--index", str(index.dir), "--top", "5", "--snippets", "1"))
    results = search(index, query)
    first, second = index.get_postings("తెలుగు"), index.get_postings("సినిమా")
    ok = True
    for r in results[:3]:
        p1, p2 = first[r.doc_id], second[r.doc_id]
        starts = [p for p in p1 if p + 1 in set(p2)]
        out.append(f"Check doc {r.doc_id}: తెలుగు at {p1[:12]}{' ...' if len(p1) > 12 else ''}, "
                   f"సినిమా at {p2[:12]}{' ...' if len(p2) > 12 else ''} -> adjacent at {starts[:12]}")
        ok &= check(out, [m[0] for m in r.matches] == starts, f"doc {r.doc_id}: every match is a position p with సినిమా at p+1")
    both = set(first) & set(second)
    out.append(f"Documents containing both words anywhere: {len(both):,}; as a phrase: {len(results):,}")
    ok &= check(out, len(results) < len(both), "the phrase matches fewer documents than AND of the two words")
    return ok


def test_proximity(index, out: list[str]) -> bool:
    query = "సినిమా /3 దర్శకత్వం"
    out += section("TEST CASE 5: Proximity query - within 3 positions, either order")
    out.append(f"$ python -m src.cli search \"{query}\" --top 5 --snippets 1")
    out.append(run_cli("search", query, "--index", str(index.dir), "--top", "5", "--snippets", "1"))
    results = search(index, query)
    first, second = index.get_postings("సినిమా"), index.get_postings("దర్శకత్వం")
    expected = {d for d in set(first) & set(second) if any(abs(p - q) <= 3 for p in first[d] for q in second[d])}
    ok = check(out, {r.doc_id for r in results} == expected,
               f"the result set equals all documents with a pair |p - q| <= 3 ({len(expected):,}, brute force)")
    r = results[0]
    pairs = [(p, q) for p in first[r.doc_id] for q in second[r.doc_id] if abs(p - q) <= 3]
    out.append(f"Check doc {r.doc_id}: (సినిమా, దర్శకత్వం) position pairs within 3: {pairs[:10]}")
    return ok & check(out, len(pairs) > 0, f"doc {r.doc_id} has at least one such pair")


def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Write output.txt: rare terms and test cases")
    parser.add_argument("--index", default="index")
    parser.add_argument("--out", type=Path, default=Path("output.txt"))
    args = parser.parse_args(argv)
    index = load_index(args.index)

    out = ["Anveshinchu: positional index over Telugu Wikipedia - output", ""]
    out.append("$ python -m src.cli stats")
    out.append(run_cli("stats", "--index", args.index))
    out += section("10 RARE TERMS WITH THEIR POSITIONAL INDEX")
    out.append("Format: doc <internal doc ID> [<Wikipedia page ID>] <article title>: tf=<occurrences in that article> "
               "positions=<word positions>")
    out.append("$ python -m src.cli rare --count 10")
    out.append(run_cli("rare", "--index", args.index, "--count", "10"))

    results = [test_storage(index, out), test_tokenizer(out), test_boolean(index, out),
               test_phrase(index, out), test_proximity(index, out)]
    out += section(f"SUMMARY: {sum(results)} of {len(results)} test cases passed")
    args.out.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({sum(results)}/{len(results)} test cases passed)")


if __name__ == "__main__":
    main()
