# Anveshinchu (అన్వేషించు)

*A Telugu full-text search engine with a positional inverted index, supporting boolean, phrase and proximity queries.*

**Anveshinchu** (అన్వేషించు, "to search / explore") indexes Telugu Wikipedia passages from the [MIRACL](https://huggingface.co/datasets/miracl/miracl) retrieval benchmark. It uses only the Python standard library.

**Sample run:** [`sample_output.md`](sample_output.md)

> The positional-index engine started as my Information Retrieval course project over Japanese literature. That graded version is preserved at the git tag [`v1.0-course-project`](https://github.com/shreeyajetti/anveshinchu/tree/v1.0-course-project).

---

## Why Telugu is interesting for search

Telugu attaches suffixes directly to words, and the stem itself can change:

| Telugu | Meaning | Passages containing this exact form |
|---|---|---:|
| ఇల్లు | house | 46 |
| ఇంటికి | to the house | 92 |
| ఇంట్లో | in the house | 79 |
| ఇంటి | of the house | 92 |

A search for ఇల్లు should find all of them (275 passages), but exact word matching finds only 46. Simply chopping off endings doesn't connect ఇల్లు with ఇంటి- either. It shows up in the vocabulary size too: this collection has **208,969 distinct terms in 1.7 million words**, because every suffixed form counts as a separate term. Closing this gap, and measuring how well it's closed, is the next stage of the project.

## The collection

MIRACL's Telugu part has 518,079 passages from 66,353 Wikipedia articles, plus test questions with passages judged relevant or not relevant by native speakers. The full collection is too large for the current in-memory JSON index, so `src/fetch_miracl.py` builds a reproducible subset:

- **1,223 articles** containing a passage judged for one of the 828 dev questions, so the questions keep their answers in the collection
- **1,223 random other articles** as distractors (fixed seed 42)
- **29,268 passages** in total, about 1.7 million words

Each passage is one document, indexed as *article title + passage text*, because passages often don't repeat the name of what they describe.

---

## The indexing pipeline

```
 passage ──► Tokenizer ──────► Normalization ─────► Indexer ──────► Inverted Index ──► Storage (JSON)
             (Unicode letter/   (remove ZWNJ/ZWJ,   (assign         term → {doc →
              mark/number runs)  NFKC, ౦-౯ → 0-9)   positions)      [positions]}
```

Documents and queries go through **the same** `analyze()` function (`tokenize` → `normalize`), so a query term always has the same form as the indexed term.

### 1. Tokenizer: `src/tokenizer.py`

Telugu puts spaces between words, but neither obvious way of splitting works:

```python
>>> "విక్రమ్‌ సారాభాయ్ 500 కి.మీ.".split()
['విక్రమ్\u200c', 'సారాభాయ్', '500', 'కి.మీ.']          # punctuation and an invisible ZWNJ stay attached

>>> re.findall(r"\w+", "విక్రమ్ సారాభాయ్ అంతరిక్ష కేంద్రం")
['వ', 'క', 'రమ', 'స', 'ర', 'భ', 'య', 'అ', 'తర', 'క', 'ష', 'క', 'ద', 'ర']   # every word shredded
```

A Telugu syllable is a consonant plus vowel signs (ా ి ీ ు …) and the virama (్). Unicode classifies these as **combining marks**, not letters. Python's `\w` doesn't count marks as word characters, so it cuts words apart at every vowel sign. Over a third of all characters in this collection (40% of the non-space ones) are such marks.

The tokenizer therefore defines a token as a maximal run of Unicode **letters, marks and numbers** (plus the zero-width joiners). Everything else (spaces, punctuation, symbols) separates tokens. Each token keeps its character offsets in the original text, for snippets.

### 2. Normalization: `src/normalizer.py`

- **Remove zero-width joiners** (U+200C ZWNJ, U+200D ZWJ). They only change how a word is *rendered*, but 17% of passages contain them. The benchmark question *హెమింగ్వే ఎప్పుడు పుట్టాడు?* ("When was Hemingway born?") writes the name without a ZWNJ, and the Wikipedia article writes it with one. Without this step the question could never find its own answer article.
- **Unicode NFKC** composes equivalent character sequences into one form (ె + ౖ → ై) and folds full-width Latin letters and digits.
- **Telugu digits → ASCII** (౨౦౧౧ → 2011), so both forms match.
- **Lowercase** Latin letters (about 10% of passages contain English words).
- **No stop-word removal and no suffix stripping yet.** Common words like ఈ ("this") stay in the index, because phrase queries need every word in the position sequence.

### 3. Indexer: `src/indexer.py`

The indexer numbers the normalized terms of each passage 0, 1, 2, … and appends each position to that term's postings.

### 4. Inverted index: the positional data model

```python
postings: dict[str, dict[int, list[int]]]   # term -> {doc_id -> sorted positions}

"గుంటూరు": {0: [0, 2, 36], 1: [0], ...}     # 458 passages in total
```

- `docs` holds per-passage metadata: the MIRACL passage ID (e.g. `786#0` = article 786, passage 0), the title and the number of terms.
- `store` holds the indexed text, used only to print snippets. Character offsets aren't stored; the snippet code re-tokenizes the one passage it displays, which reproduces the same positions.

---

## Why positional indexing?

A basic inverted index only records **which** passages contain a term. That's enough for boolean queries, but not for phrases. `తెలుగు AND సినిమా` matches any passage containing both words anywhere. The phrase `"తెలుగు సినిమా"` ("Telugu cinema") should match only where the two words are **next to each other, in that order**.

With every position stored, both kinds of query can be checked exactly:

- **Phrase** `t1 t2 … tn`: for each passage containing all terms, keep the start positions *p* where *t1* is at *p*, *t2* at *p+1*, …, *tn* at *p+n−1*.
- **Proximity** `t1 /k t2`: for each passage containing both terms, find pairs of positions with |pos(t1) − pos(t2)| ≤ k, in either order. Both position lists are sorted, so this is a **two-pointer sliding window** in O(|P1| + |P2| + matches) time.

The index stores **all** positions of a term in a passage, not only the first one. Otherwise a phrase starting at the term's second occurrence would be missed. Positions count words only: punctuation doesn't take up a position, so `"వెళ్ళాడు రాముడు"` matches *…వెళ్ళాడు. రాముడు…* across the full stop.

---

## How to use this code

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
python -m unittest -v             # 16 tests (1 expected failure documents the suffix gap)
```

Requires Python 3.10+. There are no third-party dependencies. The CLI switches the console to UTF-8 itself, because the default Windows console encoding (cp1252) can't print Telugu.

### 0. Get the data

```bash
python -m src.fetch_miracl
```

```
Collection: 66,353 articles. Kept 1,223 judged + 1,223 random articles = 29,268 passages -> data/passages.jsonl
```

This downloads about 72 MB once into `.cache/`. The generated `data/passages.jsonl` (36 MB) and the index (64 MB) are not committed to git. They are rebuilt deterministically by these commands. The dev questions and judgments (`data/topics.dev.tsv`, `data/qrels.dev.tsv`) are committed.

### 1. Storage: build the index and save it to disk

```bash
python -m src.cli build                  # defaults: --data data --index index
```

```
Loaded 29,268 passages from 2,446 articles in data/
Indexed 29,268 docs, 208,969 distinct terms, 1,347,104 postings, 1,733,583 positions in 13.27s
Saved index to index/index.json
```

**Format: JSON instead of pickle.**

- JSON is human-readable and portable across languages and Python versions.
- Loading it can't execute code. Unpickling a file can, which makes pickle unsafe for files you didn't create.

At this size the trade-off is starting to show: `index.json` is 28 MB and takes a few seconds to load. A compact on-disk format is on the roadmap.

**Telugu text encoding:**

- Every file is read and written with an explicit `encoding="utf-8"`.
- JSON is written with `ensure_ascii=False`, so terms are stored as `"గుంటూరు"` rather than `"\u0c17\u0c41\u0c02..."`. Telugu characters take 3 bytes in UTF-8 but 6 bytes as `\u` escapes, so this halves the file size.
- The file has one term per line, so it diffs cleanly. JSON object keys must be strings, so doc IDs are written as `"0"` and converted back to `int` when loading.

### 2. Retrieval: load a previously built index

`storage.load_index()` reads the JSON back into an `InvertedIndex` without re-tokenizing anything. `stats` loads the index and can print a term's positional postings:

```bash
python -m src.cli stats --term ఇల్లు ఇంటికి --limit 3
```

```
Loaded index from index/ in 1.630s (no re-tokenization)
  ...
Postings for 'ఇల్లు' (document frequency 46):
  doc 947 [1557#11] ఒడిషా: tf=1 positions=[17]
  doc 1679 [2502#3] ఇందిరా గాంధీ: tf=1 positions=[30]
  doc 2148 [3195#5] వినాయకుడు: tf=1 positions=[29]
  ... 43 more documents
```

From Python:

```python
from src.storage import load_index
from src.search import search, snippet

index = load_index("index")
for r in search(index, '"తెలుగు సినిమా"')[:3]:
    print(r.docid, r.title, r.matches, snippet(index, r.doc_id, r.matches[0]))
```

### 3. Searching: run queries against the loaded index

```bash
python -m src.cli search "QUERY"          # --top N documents, --snippets N per document
python -m src.cli search                  # interactive prompt; empty line quits
python -m src.cli tokenize "తెలుగు వాక్యం"   # show how text is tokenized and normalized
```

Add `--translit` to any command to print Telugu in Latin letters ([ISO 15919](https://en.wikipedia.org/wiki/ISO_15919)), for terminals that draw Telugu conjuncts incorrectly: `గ్రామంలో` prints as `grāmaṁlō`.

**Query syntax.** Operators are upper-case and separated by spaces:

| Query | Meaning |
|---|---|
| `గుంటూరు AND జిల్లా` | both terms in the passage |
| `గుంటూరు జిల్లా` | implicit AND |
| `ఇంటికి OR ఇంట్లో` | either term |
| `గుంటూరు AND NOT జిల్లా` | first term, but not the second |
| `(సినిమా OR నాటకం) AND నటి` | parentheses for grouping |
| `"తెలుగు సినిమా"` | **phrase**: terms adjacent, in this order |
| `సినిమా /3 దర్శకత్వం` | **proximity**: within 3 positions, either order |

Precedence: `NOT` > `AND` > `OR`. Every query word goes through the same tokenizer and normalizer as the documents, so `హెమింగ్వే` (no ZWNJ) matches `హెమింగ్‌వే` (with ZWNJ), and `౨౦౧౧` matches `2011`. An unquoted word containing punctuation (e.g. `కి.మీ`) is searched as a phrase.

> **Windows PowerShell:** PowerShell 5.1 strips double quotes inside a command-line argument, so `search '"తెలుగు సినిమా"'` arrives as `తెలుగు సినిమా` and runs as an AND query. Use `「తెలుగు సినిమా」` on the command line, or type queries at the interactive prompt, where `"..."` works as normal.

Each result shows the internal doc ID, the MIRACL passage ID, the article title and the number of matches. For each match it shows the term positions and a snippet of the original text with the match in 【】. Results are ordered by number of matches, and `NOT` excludes passages without highlighting anything.

**Phrase:**
```
$ python -m src.cli search '"తెలుగు సినిమా"' --top 2 --snippets 1
Query: "తెలుగు సినిమా"  ->  101 document(s)
  doc 20973 [92548#7] బులెమోని వెంకటేశ్వర్లు  (4 match(es))
      positions 2-3: …బులెమోని వెంకటేశ్వర్లు 【తెలుగు సినిమా】 గొప్పదనాన్ని, తెలుగు జాతి…
  doc 3232 [6185#11] తెలుగు సినిమా  (3 match(es))
      positions 0-1: …【తెలుగు సినిమా】 వాణిజ్య పరంగా సత్ఫలితాలని…
```

**Proximity:**
```
$ python -m src.cli search "సినిమా /3 దర్శకత్వం" --top 2 --snippets 1
Query: సినిమా /3 దర్శకత్వం  ->  14 document(s)
  doc 25901 [132304#7] తమన్నా  (2 match(es))
      positions 68-71: …సినిమాలో నటించింది. ఈ 【సినిమా ఎన్. లింగుసామి దర్శకత్వం】 వహించిన తమిళ్ సినిమా…
  doc 3217 [6122#2] సావిత్రి (నటి)  (1 match(es))
      positions 70-73: …వేదాంతం రాఘవయ్య 【దర్శకత్వం వహించిన దేవదాసు సినిమా】 వరకూ ఆగవలసి…
```

See [`sample_output.md`](sample_output.md) for boolean, OR-across-suffixes and normalization examples.

### 4. Evaluation: boolean AND vs BM25 ranking

```bash
python -m src.evaluate                                 # summary in the terminal
python -m src.evaluate --report reports/evaluation.md  # plus every question, with transliteration
```

Each of the 828 dev questions is turned into query terms (`src/questions.py` drops question words like ఎప్పుడు "when" and ఎంత "how much", which never occur in answers) and answered two ways:

- **AND** returns every passage containing all the terms. It is unranked, so it is scored on its whole result set.
- **BM25** (`src/ranking.py`) scores every passage containing *any* of the terms, weighting rare words more and long passages less, and returns the top 10.

| Exact terms, no stemming | Success | Recall | nDCG@10 | MRR@10 |
|---|---:|---:|---:|---:|
| AND (whole result set) | 12.7% | 12.3% | | |
| BM25 (top 10) | 62.8% | 62.5% | 0.444 | 0.390 |

*Success* = at least one relevant passage retrieved; *Recall* = share of relevant passages retrieved; nDCG@10 is MIRACL's official metric. AND returns nothing at all for 80% of questions, because a single missing word (often a differently suffixed form) empties the result.

These numbers are optimistic in absolute terms. The collection is 18× smaller than the full corpus, two thirds of its passages come from judged articles, and the question-word list was built from these same questions. Compare rows, not against published results.

---

## Limitations

- **Suffixed forms don't match** (ఇల్లు vs ఇంటికి, see above). This is the main limitation, recorded as an expected-failure test.
- **The benchmark questions don't suit boolean search.** MIRACL questions are natural sentences (*హెమింగ్వే ఎప్పుడు పుట్టాడు?*). An AND over every word, including "when" and "born", rarely matches, so they need ranked retrieval.
- **The search command doesn't rank.** BM25 is used by the evaluation, but `search` still orders boolean results by match count.
- **Subset, not the full collection.** The judged articles are guaranteed to be included, which makes the collection easier than the real 518k-passage one. Any evaluation numbers should say so.
- **Positions cross sentence boundaries.** Punctuation isn't a position, so a phrase or proximity match can span the end of one sentence and the start of the next.

## Roadmap

1. ~~**Evaluation.**~~ Done: `src/evaluate.py`, AND vs BM25 on the dev questions.
2. ~~**Ranking.**~~ Done for evaluation: `src/ranking.py`. Next: a ranked `search` mode for questions.
3. **Suffix handling.** A rule-based stemmer (`src/stemmer.py`, in progress), measured against the exact-match baseline above.
4. **Held-out evaluation.** Split the dev questions so rules are chosen on one half and measured on the other.
5. **Scale.** A compact on-disk index, then the full 518k-passage collection.

## Data and license

Passages come from Telugu Wikipedia via MIRACL ([dataset](https://huggingface.co/datasets/miracl/miracl), Apache-2.0; Wikipedia text is CC BY-SA). Xinyu Zhang et al., [*MIRACL: A Multilingual Retrieval Dataset Covering 18 Diverse Languages*](https://aclanthology.org/2023.tacl-1.63/), TACL 11 (2023), pp. 1114–1131.
