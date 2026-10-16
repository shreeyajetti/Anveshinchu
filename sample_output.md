# Sample output

Produced by running the commands shown against the MIRACL Telugu subset in `data/` (29,268 Wikipedia passages). See the [README](README.md) for the query syntax.

## 1. Building the index (Storage)

```
$ python -m src.cli build
Loaded 29,268 passages from 2,446 articles in data/
Indexed 29,268 docs, 208,969 distinct terms, 1,347,104 postings, 1,733,583 positions in 13.64s
Saved index to index/index.json
```

## 2. Tokenization of one sample sentence

The input contains an invisible zero-width non-joiner (ZWNJ, U+200C) after విక్రమ్, punctuation attached to words, and Telugu digits. The tokenizer keeps vowel signs and the virama (్) inside words and splits on punctuation; the normalizer removes the ZWNJ and turns ౨౦౧౧ into 2011.

```
$ python -m src.cli tokenize 'విక్రమ్ సారాభాయ్ అంతరిక్ష కేంద్రం, 500 కి.మీ. ఎత్తు (౨౦౧౧).'
Input: విక్రమ్<ZWNJ> సారాభాయ్ అంతరిక్ష కేంద్రం, 500 కి.మీ. ఎత్తు (౨౦౧౧).

1. Tokenizer (runs of Unicode letters, vowel signs/marks, numbers):
   విక్రమ్<ZWNJ> | సారాభాయ్ | అంతరిక్ష | కేంద్రం | 500 | కి | మీ | ఎత్తు | ౨౦౧౧
     0-8   విక్రమ్<ZWNJ>   [0C35 0C3F 0C15 0C4D 0C30 0C2E 0C4D 200C]
     9-17  సారాభాయ్   [0C38 0C3E 0C30 0C3E 0C2D 0C3E 0C2F 0C4D]
    18-26  అంతరిక్ష   [0C05 0C02 0C24 0C30 0C3F 0C15 0C4D 0C37]
    27-34  కేంద్రం   [0C15 0C47 0C02 0C26 0C4D 0C30 0C02]
    36-39  500   [0035 0030 0030]
    40-42  కి   [0C15 0C3F]
    43-45  మీ   [0C2E 0C40]
    47-52  ఎత్తు   [0C0E 0C24 0C4D 0C24 0C41]
    54-58  ౨౦౧౧   [0C68 0C66 0C67 0C67]

2. Normalizer (remove ZWNJ/ZWJ, NFKC, Telugu digits -> 0-9, lowercase) -> index terms with positions:
   0:విక్రమ్  1:సారాభాయ్  2:అంతరిక్ష  3:కేంద్రం  4:500  5:కి  6:మీ  7:ఎత్తు  8:2011
```

## 3. Loading the saved index (Retrieval) and inspecting positional postings

ఇల్లు (house) and ఇంటికి (to the house) are different terms: exact-form matching treats suffixed forms as separate words.

```
$ python -m src.cli stats --term ఇల్లు ఇంటికి --limit 3
Loaded index from index/ in 1.586s (no re-tokenization)
  language: Telugu
  collection: MIRACL v1.0 Telugu (subset)
  tokenizer: Unicode letter/mark/number runs
  normalization: remove ZWNJ/ZWJ, NFKC, Telugu digits -> ASCII, lowercase
  num_docs: 29268
  num_terms: 208969
  num_postings: 1347104
  num_positions: 1733583

Postings for 'ఇల్లు' (document frequency 46):
  doc 947 [1557#11] ఒడిషా: tf=1 positions=[17]
  doc 1679 [2502#3] ఇందిరా గాంధీ: tf=1 positions=[30]
  doc 2148 [3195#5] వినాయకుడు: tf=1 positions=[29]
  ... 43 more documents

Postings for 'ఇంటికి' (document frequency 92):
  doc 187 [859#36] అన్నమయ్య: tf=1 positions=[10]
  doc 267 [875#10] శ్రీ కృష్ణుడు: tf=1 positions=[32]
  doc 268 [875#11] శ్రీ కృష్ణుడు: tf=1 positions=[43]
  ... 89 more documents
```

## 4. Example queries (Search)

### Boolean: AND / NOT

```
$ python -m src.cli search 'గుంటూరు AND జిల్లా' --top 3 --snippets 1
Query: గుంటూరు AND జిల్లా  ->  195 document(s)
  doc 0 [786#0] గుంటూరు జిల్లా  (8 match(es))
      positions 0-0: …【గుంటూరు】 జిల్లా గుంటూరు జిల్లా 11,391…
      ... 7 more
  doc 6 [786#6] గుంటూరు జిల్లా  (7 match(es))
      positions 0-0: …【గుంటూరు】 జిల్లా 687లో ఔరంగజేబు…
      ... 6 more
  doc 439 [1306#3] ప్రకాశం జిల్లా  (7 match(es))
      positions 1-1: …ప్రకాశం 【జిల్లా】 స్వాతంత్ర్యోద్యమ సమయంలో…
      ... 6 more
  ... 192 more documents (use --top to show more)
```

```
$ python -m src.cli search 'గుంటూరు AND NOT జిల్లా' --top 3 --snippets 1
Query: గుంటూరు AND NOT జిల్లా  ->  263 document(s)
  doc 12145 [34399#5] వింజనం పాడు  (11 match(es))
      positions 48-48: …అధ్యక్షులు. [6] [1] ఈనాడు 【గుంటూరు】 సిటీ/ప్రత్తిపాడు;…
      ... 10 more
  doc 11901 [34233#23] వరగాణి  (8 match(es))
      positions 9-9: …గణాంకాల జాలగూడు [2] ఈనాడు 【గుంటూరు】 సిటీ/ప్రత్తిపాడు; 2013,…
      ... 7 more
  doc 11705 [34132#24] చిలువూరు  (7 match(es))
      positions 33-33: …1,784 హెక్టారులు. [3] ఈనాడు 【గుంటూరు】 సిటీ/మంగళగిరి;…
      ... 6 more
  ... 260 more documents (use --top to show more)
```

### Boolean: OR across suffixed forms

ఇల్లు alone matches 46 passages; OR-ing in its suffixed forms by hand finds 275. Doing this automatically is the next stage of the project.

```
$ python -m src.cli search 'ఇల్లు OR ఇంటికి OR ఇంట్లో OR ఇంటి' --top 3 --snippets 1
Query: ఇల్లు OR ఇంటికి OR ఇంట్లో OR ఇంటి  ->  275 document(s)
  doc 25622 [124183#5] పల్లెల్లో కులవృత్తులు  (5 match(es))
      positions 16-16: …కాడిమాను, ఎద్దుల బండి, 【ఇంటి】 సామానులు తయారు చేయడం వీరి…
      ... 4 more
  doc 17101 [53329#0] శ్రీను వైట్ల  (4 match(es))
      positions 201-201: …నెలలకే ఫీజులు కట్టడానికని 【ఇంట్లో】 ఇచ్చిన డబ్బులు జేబులో…
      ... 3 more
  doc 25618 [124183#1] పల్లెల్లో కులవృత్తులు  (4 match(es))
      positions 72-72: …మధ్యాహ్నం ఒకరు వచ్చి ప్రతి 【ఇంటి】 వద్ద కొంత అన్నం కూర తీసుకుని…
      ... 3 more
  ... 272 more documents (use --top to show more)
```

### Phrase

Matches only where తెలుగు is immediately followed by సినిమా (positions p, p+1).

```
$ python -m src.cli search '"తెలుగు సినిమా"' --top 3 --snippets 1
Query: "తెలుగు సినిమా"  ->  101 document(s)
  doc 20973 [92548#7] బులెమోని వెంకటేశ్వర్లు  (4 match(es))
      positions 2-3: …బులెమోని వెంకటేశ్వర్లు 【తెలుగు సినిమా】 గొప్పదనాన్ని, తెలుగు జాతి…
      ... 3 more
  doc 3232 [6185#11] తెలుగు సినిమా  (3 match(es))
      positions 0-1: …【తెలుగు సినిమా】 వాణిజ్య పరంగా సత్ఫలితాలని…
      ... 2 more
  doc 20969 [92548#3] బులెమోని వెంకటేశ్వర్లు  (3 match(es))
      positions 5-6: …బులెమోని రచించిన "【తెలుగు సినిమా】 చరిత్ర", "తెలుగు సినిమా…
      ... 2 more
  ... 98 more documents (use --top to show more)
```

### Proximity

సినిమా (film) and దర్శకత్వం (direction) within 3 positions of each other, in either order.

```
$ python -m src.cli search 'సినిమా /3 దర్శకత్వం' --top 3 --snippets 1
Query: సినిమా /3 దర్శకత్వం  ->  14 document(s)
  doc 25901 [132304#7] తమన్నా  (2 match(es))
      positions 68-71: …సినిమాలో నటించింది. ఈ 【సినిమా ఎన్. లింగుసామి దర్శకత్వం】 వహించిన తమిళ్ సినిమా…
      ... 1 more
  doc 3217 [6122#2] సావిత్రి (నటి)  (1 match(es))
      positions 70-73: …అయిన వేదాంతం రాఘవయ్య 【దర్శకత్వం వహించిన దేవదాసు సినిమా】 వరకూ ఆగవలసి వచింది. ఎల్వీ…
  doc 3487 [6790#16] ఘట్టమనేని కృష్ణ  (1 match(es))
      positions 70-73: …బాధపడింది. ప్రస్తుతం ఆమె 【సినిమా నిర్మాణం, నటన, దర్శకత్వం】 కూడా చేస్తోంది. 2012లో కృష్ణ…
  ... 11 more documents (use --top to show more)
```

### Normalization at query time

The query is typed without a ZWNJ, as in the benchmark question హెమింగ్వే ఎప్పుడు పుట్టాడు?, while the article spells it హెమింగ్‌వే with one. Both normalize to the same term.

```
$ python -m src.cli search హెమింగ్వే --top 2 --snippets 1
Query: హెమింగ్వే  ->  50 document(s)
  doc 22923 [105922#10] ఎర్నెస్ట్ హెమింగ్‌వే  (14 match(es))
      positions 1-1: …ఎర్నెస్ట్ 【హెమింగ్‌వే】 హెమింగ్‌వే అంతకుముందు…
      ... 13 more
  doc 22958 [105922#45] ఎర్నెస్ట్ హెమింగ్‌వే  (12 match(es))
      positions 1-1: …ఎర్నెస్ట్ 【హెమింగ్‌వే】 హెమింగ్‌వే ప్రేరణ వ్యాప్తి…
      ... 11 more
  ... 48 more documents (use --top to show more)
```
