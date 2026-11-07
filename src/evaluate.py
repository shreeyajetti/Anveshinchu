"""Evaluation on the MIRACL Telugu dev questions: boolean AND vs BM25.

    python -m src.cli build --source miracl --index index-miracl   # once
    python -m src.evaluate [--index index-miracl] [--data data] [--report reports/evaluation.md]

Each question is turned into terms with questions.question_terms() (question
words dropped), then answered two ways:

- AND:   passages containing every term. Unranked, so it is scored on its
         whole result set, however large; this flatters AND.
- BM25:  the 10 highest-scoring passages (ranking.BM25).

Metrics (macro-averaged over questions; a passage counts as relevant if
MIRACL judged it relevant):

- Success: at least one relevant passage retrieved (top 10 for BM25)
- Recall:  share of a question's relevant passages retrieved
- nDCG@10: rewards relevant passages near the top (log2 rank discount),
           MIRACL's official metric
- MRR@10:  1 / rank of the first relevant passage (0 if none in the top 10)

If src/stemmer.py exists and defines stem(term) -> str, every run is also
repeated with stemming. Stemming is applied to the index here by merging the
postings of all terms that share a stem, so no rebuild is needed.
"""

import argparse
import math
import statistics
import sys
from pathlib import Path

from .indexer import InvertedIndex
from .questions import question_terms
from .ranking import BM25
from .storage import load_index
from .translit import transliterate

K = 10


def load_topics(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        return dict(line.rstrip("\n").split("\t", 1) for line in f)


def load_qrels(path: Path) -> dict[str, set[str]]:
    """Relevant passage IDs per question (judgments of 0 are ignored)."""
    relevant: dict[str, set[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            qid, _, docid, rel = line.split()
            if rel == "1":
                relevant.setdefault(qid, set()).add(docid)
    return relevant


def stem_index(index: InvertedIndex, stem) -> InvertedIndex:
    """A copy of the index whose terms are stems; positions are merged, so phrases still work."""
    postings: dict[str, dict[int, list[int]]] = {}
    for term, docs in index.iter_postings():
        merged = postings.setdefault(stem(term), {})
        for doc_id, positions in docs.items():
            merged.setdefault(doc_id, []).extend(positions)
    for docs in postings.values():
        for positions in docs.values():
            positions.sort()
    return InvertedIndex(index.meta, index.docs, postings, index.store)


def boolean_and(index: InvertedIndex, terms: list[str]) -> set[int]:
    if not terms:
        return set()
    postings = sorted((index.get_postings(t) for t in set(terms)), key=len)
    return set(postings[0]).intersection(*postings[1:])


def ndcg(ranked: list[int], relevant: set[int], k: int = K) -> float:
    dcg = sum(1 / math.log2(rank + 1) for rank, d in enumerate(ranked[:k], 1) if d in relevant)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


def first_relevant_rank(ranked: list[int], relevant: set[int]) -> int | None:
    return next((rank for rank, d in enumerate(ranked, 1) if d in relevant), None)


def run(index: InvertedIndex, topics: dict[str, str], qrels: dict[str, set[str]], stem=None) -> dict:
    """Evaluate AND and BM25 on every question; returns summary metrics and per-question rows."""
    if stem is not None:
        index = stem_index(index, stem)
    to_id = {info["docid"]: d for d, info in index.docs.items()}
    bm25 = BM25(index)
    rows = []
    for qid, question in topics.items():
        terms = question_terms(question)
        if stem is not None:
            terms = [stem(t) for t in terms]
        relevant = {to_id[docid] for docid in qrels.get(qid, ()) if docid in to_id}
        if not relevant:
            continue
        and_docs = boolean_and(index, terms)
        ranked = [d for d, _ in bm25.top(terms, K)]
        rank = first_relevant_rank(ranked, relevant)
        rows.append({
            "qid": qid,
            "question": question,
            "terms": terms,
            "and_size": len(and_docs),
            "and_success": bool(and_docs & relevant),
            "and_recall": len(and_docs & relevant) / len(relevant),
            "bm25_success": rank is not None,
            "bm25_recall": len(set(ranked) & relevant) / len(relevant),
            "bm25_ndcg": ndcg(ranked, relevant),
            "bm25_rr": 1 / rank if rank else 0.0,
            "bm25_rank": rank,
            "bm25_top": index.docs[ranked[0]]["title"] if ranked else "",
        })
    mean = lambda key: statistics.mean(r[key] for r in rows)  # noqa: E731
    summary = {
        "questions": len(rows),
        "and_success": mean("and_success"),
        "and_recall": mean("and_recall"),
        "and_empty": statistics.mean(r["and_size"] == 0 for r in rows),
        "and_median_size": statistics.median(r["and_size"] for r in rows),
        "bm25_success": mean("bm25_success"),
        "bm25_recall": mean("bm25_recall"),
        "bm25_ndcg": mean("bm25_ndcg"),
        "bm25_mrr": mean("bm25_rr"),
    }
    return {"summary": summary, "rows": rows}


def print_summary(name: str, s: dict) -> None:
    n = s["questions"]
    print(f"\n{name} ({n} questions)")
    print(f"  AND (whole result set):  success {s['and_success']:.1%} ({round(s['and_success'] * n)}), "
          f"recall {s['and_recall']:.1%}, empty {s['and_empty']:.1%}, median size {s['and_median_size']:g}")
    print(f"  BM25 top {K}:             success {s['bm25_success']:.1%} ({round(s['bm25_success'] * n)}), "
          f"recall {s['bm25_recall']:.1%}, nDCG@{K} {s['bm25_ndcg']:.3f}, MRR@{K} {s['bm25_mrr']:.3f}")


def write_report(path: Path, results: dict[str, dict]) -> None:
    """Markdown report: summary per configuration, then every question with its outcome."""
    names = list(results)
    lines = ["# Evaluation: boolean AND vs BM25\n",
             "MIRACL Telugu dev questions, question words removed. Transliteration in *italics* (ISO 15919).\n",
             "| Configuration | AND success | AND recall | AND empty | BM25 Success@10 | BM25 Recall@10 | nDCG@10 | MRR@10 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in names:
        s = results[name]["summary"]
        lines.append(f"| {name} | {s['and_success']:.1%} | {s['and_recall']:.1%} | {s['and_empty']:.1%} | "
                     f"{s['bm25_success']:.1%} | {s['bm25_recall']:.1%} | {s['bm25_ndcg']:.3f} | {s['bm25_mrr']:.3f} |")
    lines += ["\n## Per question\n",
              "AND: result-set size, ✓ if it contains a relevant passage. BM25: rank of the first relevant passage in the top 10.\n",
              "| QID | Question | " + " | ".join(f"{n}: AND | {n}: BM25" for n in names) + " | BM25 top result (last config) |",
              "|---|---|" + "---:|---:|" * len(names) + "---|"]
    by_qid = [{r["qid"]: r for r in results[n]["rows"]} for n in names]
    for qid, row in by_qid[-1].items():
        cells = []
        for rows in by_qid:
            r = rows[qid]
            cells.append(f"{r['and_size']:,}{' ✓' if r['and_success'] else ''}")
            cells.append(str(r["bm25_rank"]) if r["bm25_rank"] else "—")
        q, top = row["question"], row["bm25_top"]
        lines.append(f"| {qid} | {q} *({transliterate(q)})* | " + " | ".join(cells) + f" | {top} *({transliterate(top)})* |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate boolean AND and BM25 on the MIRACL Telugu dev questions")
    parser.add_argument("--index", default="index-miracl", help="index built with --source miracl")
    parser.add_argument("--data", default="data")
    parser.add_argument("--report", type=Path, help="write a Markdown report with every question to this path")
    args = parser.parse_args(argv)

    index = load_index(args.index)
    topics = load_topics(Path(args.data) / "topics.dev.tsv")
    qrels = load_qrels(Path(args.data) / "qrels.dev.tsv")
    configs = {"exact": None}
    try:
        from .stemmer import stem
        configs["stemmed"] = stem
    except ImportError:
        print("(src/stemmer.py not found: evaluating without stemming only)")
    results = {name: run(index, topics, qrels, stem) for name, stem in configs.items()}
    for name, r in results.items():
        print_summary(name, r["summary"])
    if args.report:
        write_report(args.report, results)
        print(f"\nWrote {args.report.as_posix()}")


if __name__ == "__main__":
    main()
