"""Ranked retrieval with BM25 (Robertson & Zaragoza, 2009).

Boolean search answers "which passages match?"; BM25 answers "which passages
match best?". A passage does not need every query word: each word it
contains adds to its score, and rare words add more than common ones.

    score(D, Q) = sum over query terms t in D of
                  idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * |D| / avgdl))

    idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5))

- tf     how often t occurs in passage D (the length of its position list)
- df     how many passages contain t
- |D|    passage length in terms; avgdl is the average passage length
- k1     how quickly repeated occurrences stop adding score (1.2)
- b      how strongly long passages are penalized (0.75)

Everything comes from the positional index that already exists: tf is
len(positions), |D| is docs[d]["num_terms"]. The idf variant is the one used
by Lucene, which never goes negative for very common words.
"""

import heapq
import math

from .indexer import InvertedIndex


class BM25:
    def __init__(self, index: InvertedIndex, k1: float = 1.2, b: float = 0.75):
        self.index, self.k1, self.b = index, k1, b
        self.n = len(index.docs)
        self.avgdl = sum(d["num_terms"] for d in index.docs.values()) / self.n

    def idf(self, term: str) -> float:
        df = len(self.index.get_postings(term))
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, terms: list[str]) -> dict[int, float]:
        """BM25 score of every passage containing at least one of the terms."""
        scores: dict[int, float] = {}
        for term in dict.fromkeys(terms):  # each distinct query term counts once
            idf = self.idf(term)
            for doc_id, positions in self.index.get_postings(term).items():
                tf = len(positions)
                length_norm = 1 - self.b + self.b * self.index.docs[doc_id]["num_terms"] / self.avgdl
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf * (self.k1 + 1) / (tf + self.k1 * length_norm)
        return scores

    def top(self, terms: list[str], k: int = 10) -> list[tuple[int, float]]:
        """The k best (doc_id, score) pairs, highest first; ties broken by doc ID."""
        return heapq.nsmallest(k, ((d, s) for d, s in self.scores(terms).items()), key=lambda x: (-x[1], x[0]))
