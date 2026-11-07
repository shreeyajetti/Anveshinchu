"""Read articles from a Wikipedia XML dump (tewiki-*-pages-articles.xml.bz2).

The dump is a single XML file containing every Telugu Wikipedia page as raw
wiki markup. It is streamed straight from the .bz2 file with iterparse, one
<page> at a time, so memory use stays flat however large the dump is.

Kept: articles (namespace 0) that are not redirects.
Skipped: redirects, talk pages, user pages, templates, categories, files, ...

Wiki markup is reduced to plain text by clean_wikitext():

    '''గుంటూరు''' [[ఆంధ్ర ప్రదేశ్]] లోని ఒక [[నగరం|నగరము]].<ref>...</ref>
    {{Infobox ...}}  [[వర్గం:నగరాలు]]
        ->  గుంటూరు ఆంధ్ర ప్రదేశ్ లోని ఒక నగరము.

Templates ({{...}}), tables ({|...|}), references, comments, files, categories
and HTML tags are removed; [[target|label]] links keep only the label.
The names of the File and Category namespaces (e.g. దస్త్రం, వర్గం) are read
from the dump's own <siteinfo>, so they don't have to be hard-coded.
"""

import bz2
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from .indexer import Document

COMMENT = re.compile(r"<!--.*?-->", re.S)
REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
NON_TEXT_TAGS = re.compile(
    r"<(math|chem|gallery|timeline|score|syntaxhighlight|source|pre|code|imagemap|graph|mapframe)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
TABLE = re.compile(r"\{\|(?:(?!\{\|).)*?\|\}", re.S)
LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
EXTERNAL_LINK = re.compile(r"\[(?:https?:)?//[^\s\]]+\s*([^\]]*)\]")
URL = re.compile(r"https?://\S+")
BOLD_ITALIC = re.compile(r"'{2,}")
HEADING = re.compile(r"^=+\s*(.*?)\s*=+\s*$", re.M)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
LIST_MARKER = re.compile(r"^[*#:;]+\s*", re.M)
TABLE_LINE = re.compile(r"^\s*[|!].*$", re.M)
MAGIC_WORD = re.compile(r"__[A-Z]+__")
INTERLANGUAGE = re.compile(r"^:?[a-z]{2,3}(-[a-z]+)*$")
BLANK_LINES = re.compile(r"\n\s*\n+")


def _remove_nested(pattern: re.Pattern, text: str) -> str:
    """Remove innermost matches repeatedly, so nested {{...{{...}}...}} goes too."""
    while True:
        new = pattern.sub("", text)
        if new == text:
            return text
        text = new


def clean_wikitext(text: str, skip_namespaces: frozenset[str]) -> str:
    """Wiki markup -> plain text. skip_namespaces: lower-cased link prefixes to drop (files, categories)."""

    def link(m: re.Match) -> str:
        target, _, label = m.group(1).partition("|")
        prefix = target.split(":", 1)[0].strip().lower() if ":" in target else ""
        if prefix in skip_namespaces or (prefix and INTERLANGUAGE.match(prefix)):
            return ""
        return (label.rsplit("|", 1)[-1] if label else target).strip()

    text = COMMENT.sub("", text)
    text = REF.sub("", text)
    text = NON_TEXT_TAGS.sub("", text)
    text = _remove_nested(TEMPLATE, text)
    text = _remove_nested(TABLE, text)
    while True:  # innermost links first, so links inside image captions resolve before the image is dropped
        new = LINK.sub(link, text)
        if new == text:
            break
        text = new
    text = EXTERNAL_LINK.sub(r"\1", text)
    text = URL.sub("", text)
    text = BOLD_ITALIC.sub("", text)
    text = HEADING.sub(r"\1", text)
    text = HTML_TAG.sub("", text)
    text = html.unescape(text)
    text = LIST_MARKER.sub("", text)
    text = TABLE_LINE.sub("", text)
    text = MAGIC_WORD.sub("", text)
    return BLANK_LINES.sub("\n", text).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]  # strip the XML namespace: {http://...}page -> page


def iter_articles(dump_path: str | Path, min_chars: int = 1) -> Iterator[Document]:
    """Yield every article of the dump as a Document with consecutive doc IDs (0, 1, 2, ...)."""
    skip = {"file", "image", "media", "category"}
    doc_id = 0
    with bz2.open(dump_path, "rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            tag = _local(elem.tag)
            if tag == "namespace" and elem.get("key") in ("6", "14", "-2") and elem.text:
                skip.add(elem.text.strip().lower())  # local names, e.g. దస్త్రం (File), వర్గం (Category)
            elif tag == "page":
                fields = {_local(child.tag): child for child in elem}
                if fields["ns"].text == "0" and "redirect" not in fields:
                    title = fields["title"].text or ""
                    text_elem = fields["revision"].find("{*}text")
                    raw = (text_elem.text or "") if text_elem is not None else ""
                    text = clean_wikitext(raw, frozenset(skip))
                    if len(text) >= min_chars:
                        yield Document(doc_id, fields["id"].text, title, text)
                        doc_id += 1
                elem.clear()  # free the page's XML subtree; keeps memory flat
