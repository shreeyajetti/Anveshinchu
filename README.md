# Anveshinchu (అన్వేషించు)

**Assignment A1: Positional Index** · Information Retrieval, M2026 · Roll number **S20240010225**

A positional inverted index over the whole Telugu Wikipedia. The vocabulary, with document and collection frequencies, is kept in main memory; the postings lists are kept on disk. Python standard library only.

| | |
|---|---|
| Language | Telugu |
| Data | Telugu Wikipedia XML dump `tewiki-20261101-pages-articles.xml.bz2`: 130,227 articles |
| Index | 1,932,309 terms · 31,586,378 postings · 52,527,950 positions |
| Memory / disk | vocabulary in memory ≈ 250 MB · postings on disk 452 MB |
| Index and data download | [GitHub release `a1-index`](https://github.com/shreeyajetti/Anveshinchu/releases/tag/a1-index) |
| Output | [`output.txt`](output.txt): 10 rare terms with their positional index, 5 test cases |

## Requirements

| Requirement | Done in | Details |
|---|---|---|
| **(a)** Wikipedia dump: one XML file with all articles of an Indian language | `src/wikidump.py` | [(a) Data](#a-data-telugu-wikipedia-dump) |
| **(b)** Crawled dataset | not used | (a) was chosen instead |
| **(c)** Positional index with collection frequency and document frequency | `src/indexer.py`, `index/vocabulary.tsv` | [(c) Positional index](#c-positional-index-with-collection-and-document-frequency) |
| **(d)** Vocabulary in main memory, entire postings list on secondary memory | `src/storage.py` | [(d) Vocabulary in memory, postings on disk](#d-vocabulary-in-main-memory-postings-on-secondary-memory) |
| README: how to run, description of each module | this file | [How to run](#how-to-run) · [Modules](#modules) |
| Output: 5 test cases, 10 rare terms with their positional index | `src/make_output.py` | [`output.txt`](output.txt) · [Output](#output) |

---

## (a) Data: Telugu Wikipedia dump

- **File:** [`tewiki-20261101-pages-articles.xml.bz2`](https://dumps.wikimedia.org/tewiki/20261101/), the official Wikimedia dump, a single XML file with every Telugu Wikipedia page (269 MB, SHA-1 `4c7c149f7ba26fa352778ea3af062071c536299b`).
- **Documents:** all 130,227 articles, i.e. pages in the main namespace that are not redirects. One document = one article (title + text).
- **Reading:** the dump is streamed from the `.bz2` file page by page (`xml.etree.ElementTree.iterparse`); it is never decompressed or loaded whole.
- **Cleaning:** wiki markup is reduced to plain text. Templates, tables, references, images, categories and HTML tags are removed; links keep their label.

```
'''గుంటూరు''' [[ఆంధ్ర ప్రదేశ్]] లోని ఒక [[నగరం|నగరము]].<ref>...</ref> {{Infobox ...}} [[వర్గం:నగరాలు]]
    ->  గుంటూరు ఆంధ్ర ప్రదేశ్ లోని ఒక నగరము.
```

## (c) Positional index with collection and document frequency

Every term of every article gets its word position (0, 1, 2, …), and **all** positions are stored in the term's postings list:

```
term -> { doc_id -> [position, position, ...] }
```

For each term in the vocabulary:

- **Document frequency (df)** = number of articles containing the term
- **Collection frequency (cf)** = total occurrences of the term in the whole collection

Both are stored with the term in `index/vocabulary.tsv`. Example from the built index:

```
vocabulary.tsv   గుంటూరు  3005  5723  145145863  37844        (term, df, cf, offset, length)
postings.txt     గుంటూరు  1:0,2,12,49,61,80,...;2:457,2876,3387,3804,4566;16:1012;...
```

గుంటూరు occurs in 3,005 articles (df) and 5,723 times in total (cf); in article 1 it is at positions 0, 2, 12, 49, …

The positions are what make phrase and proximity search possible: `"తెలుగు సినిమా"` matches only where సినిమా is at position *p+1* of తెలుగు at *p*.

## (d) Vocabulary in main memory, postings on secondary memory

| File | Contents | Kept in |
|---|---|---|
| `vocabulary.tsv` | term, df, cf, offset, length | **main memory** (≈ 250 MB with the document table) |
| `postings.txt` | one line per term: `term TAB doc:pos,pos;doc:pos;...` | **disk** (452 MB), never loaded whole |
| `docs.tsv` | doc ID, Wikipedia page ID, length, title | main memory |
| `store.jsonl` | article texts, for result snippets | disk |

**Reading a postings list:** the term is looked up in the in-memory vocabulary, the program **seeks** to its `offset` in `postings.txt` and reads exactly `length` bytes. No other part of the postings file is read.

**Building the index** (SPIMI, single-pass in-memory indexing), so that the postings never need to fit in memory:

1. Articles are indexed into an in-memory block until it holds 2 million positions.
2. The block is written to disk, sorted by term, and the memory is freed.
3. The 27 blocks are merged into `postings.txt` and `vocabulary.tsv` in one pass (k-way merge).

The whole build ran on a machine with under 3 GB of free RAM.

---

## Modules

| Module | Role |
|---|---|
| `src/wikidump.py` | **(a)** Streams the XML dump and converts wiki markup to plain text. |
| `src/tokenizer.py` | Splits text into words: runs of Unicode letters, vowel signs and numbers. (Python's `\w` would cut Telugu words apart at every vowel sign.) |
| `src/normalizer.py` | Normalizes words into index terms: removes invisible zero-width joiners, Unicode NFKC, Telugu digits → 0-9, lowercase. Used for both documents and queries. |
| `src/indexer.py` | **(c)** Records the positions of every term in every document; df and cf. |
| `src/storage.py` | **(d)** Builds the disk index in blocks and merges them; loads the vocabulary into memory and reads postings from disk by seek. |
| `src/query.py` | Parses queries: AND, OR, NOT, parentheses, "phrases", `/k` proximity. |
| `src/search.py` | Answers queries using the positional postings, with snippets. |
| `src/cli.py` | Command line: `build`, `stats`, `rare`, `search`, `tokenize`. |
| `src/make_output.py` | Generates `output.txt`. |
| `tests/` | 37 unit tests, including the disk index (multi-block merge, df/cf, seek) and the dump reader. |

Extra modules, not part of the assignment: `ranking.py`, `evaluate.py`, `questions.py`, `fetch_miracl.py`, `translit.py` (see [Extras](#extras)).

---

## How to run

Requires Python 3.10+; no third-party packages.

**1. Setup and tests**

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
python -m unittest -v
```

**2. Get the data** (or download it from the [release](https://github.com/shreeyajetti/Anveshinchu/releases/tag/a1-index))

```bash
mkdir -p .cache/tewiki
curl -L -o .cache/tewiki/tewiki-20261101-pages-articles.xml.bz2 https://dumps.wikimedia.org/tewiki/20261101/tewiki-20261101-pages-articles.xml.bz2
```

**3. Build the index** (about 23 minutes), or unzip the prebuilt index from the release into the project folder

```bash
python -m src.cli build
```

```
Indexed 130,227 docs, 1,932,309 distinct terms, 31,586,378 postings, 52,527,950 positions in 1349.56s (27 blocks merged in 37.4s)
Saved index to index/
```

**4. Look up terms**: df, cf and positional postings

```bash
python -m src.cli stats --term గుంటూరు --limit 3
python -m src.cli rare --count 10          # 10 random rare terms (df <= 3)
```

```
Loaded vocabulary (1,932,309 terms) and document table from index/ in 2.1s; postings stay on disk
Term 'గుంటూరు': document frequency (df) 3,005, collection frequency (cf) 5,723
  doc 1 [786] గుంటూరు జిల్లా: tf=31 positions=[0, 2, 12, 49, 61, 80, 89, 183, 234, 265, ...]
  doc 2 [787] ఆంధ్రప్రదేశ్: tf=5 positions=[457, 2876, 3387, 3804, 4566]
  doc 16 [829] తెలుగు: tf=1 positions=[1012]
  ... 3,002 more documents
```

**5. Search**

```bash
python -m src.cli search "గుంటూరు AND జిల్లా"       # boolean: AND, OR, NOT, ( )
python -m src.cli search "「తెలుగు సినిమా」"          # phrase (or "..." at the interactive prompt)
python -m src.cli search "సినిమా /3 దర్శకత్వం"      # proximity: within 3 positions
python -m src.cli search                           # interactive prompt
```

**6. Generate the output file**

```bash
python -m src.make_output                  # writes output.txt
```

## Output

[`output.txt`](output.txt) contains:

- **10 rare terms with their positional index:** each with df, cf and every (document, positions) entry. They are chosen at random with a fixed seed from the 395,815 Telugu terms with df ≤ 3.
- **5 test cases,** each checking its result independently against the postings read from disk (all pass):

| # | Test | Checks |
|---|---|---|
| 1 | **(d)** Vocabulary in memory, postings on disk | the vocabulary offset points exactly at the term's postings line; df and cf match the postings |
| 2 | Tokenizer and normalizer | zero-width joiner, punctuation and Telugu digits are handled |
| 3 | Boolean query `గుంటూరు AND జిల్లా AND NOT ప్రకాశం` | result equals the set operations on the postings lists |
| 4 | Phrase query `"తెలుగు సినిమా"` | every match has the second word at the next position |
| 5 | Proximity query `సినిమా /3 దర్శకత్వం` | result equals a brute-force check of all position pairs |

---

## Extras

Not part of the assignment:

- **BM25 ranking and evaluation** (`ranking.py`, `evaluate.py`) on the [MIRACL](https://huggingface.co/datasets/miracl/miracl) Telugu benchmark questions, which needs its own small MIRACL index (`python -m src.fetch_miracl`, `python -m src.cli build --source miracl --index index-miracl`, `python -m src.evaluate`). BM25 finds a relevant passage in the top 10 for 62.8% of the 828 questions, against 12.7% for boolean AND.
- **`--translit`** on any command prints Telugu in Latin letters, for terminals that can't display Telugu.

## Limitations

- **Suffixed forms are separate terms** (ఇల్లు "house", ఇంటికి "to the house"); there is no stemming yet.
- **Markup cleaning is regex-based,** so a few wiki fragments survive in unusual articles.
- **The postings file is plain text,** not compressed, so that it can be read and checked by hand.

## License

Telugu Wikipedia text: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). MIRACL: Apache-2.0 (Zhang et al., [TACL 2023](https://aclanthology.org/2023.tacl-1.63/)).
