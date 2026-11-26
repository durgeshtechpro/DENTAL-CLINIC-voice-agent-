"""Load the clinic FAQ and find the sections that match a question."""

import math
import string
from pathlib import Path
from typing import Any

# Words that appear in almost every question and should not decide a match.
_STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "it",
    "this",
    "that",
    "at",
    "by",
    "from",
    "as",
    "do",
    "does",
    "did",
    "what",
    "when",
    "where",
    "how",
    "can",
    "i",
    "we",
    "you",
    "your",
    "our",
    "me",
    "my",
    "about",
    "please",
    "tell",
    "there",
    "have",
    "has",
    "any",
    "if",
}
# BM25 knobs. k1 controls how much a repeated word matters. b controls length.
_K1 = 1.5
_B = 0.75
# A best score under this means the question is not really in the document.
_SCORE_MIN = 1.0
_PUNCTUATION = str.maketrans({mark: " " for mark in string.punctuation})
_KB_DIR = Path(__file__).resolve().parent / "kb"
_INDEXES: dict[str, dict[str, Any]] = {}


# Keep a knowledge-base name that can only point at one file in agent/kb.
def _safe_name(name: str) -> str | None:
    cleaned = name.strip()
    if not cleaned:
        return None
    if not all(character.isalnum() or character in "-_" for character in cleaned):
        return None
    return cleaned


# The markdown file for one knowledge-base name, next to this module.
def kb_file(name: str) -> Path | None:
    safe = _safe_name(name)
    if safe is None:
        return None
    path = _KB_DIR / f"{safe}.md"
    if not path.is_file():
        return None
    return path


# Turn text into lowercase words, without punctuation or stop words.
def _tokens(text: str) -> list[str]:
    cleaned = text.lower().translate(_PUNCTUATION)
    return [word for word in cleaned.split() if word and word not in _STOP_WORDS]


# Split markdown into sections. Each heading starts a new section.
def _sections(markdown: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    title: str | None = None
    body: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if title is not None:
                sections.append({"title": title, "text": "\n".join(body).strip()})
            title = line.lstrip("#").strip()
            body = []
            continue
        if title is not None:
            body.append(line)
    if title is not None:
        sections.append({"title": title, "text": "\n".join(body).strip()})
    return [section for section in sections if section["title"] and section["text"]]


# How rare a word is across the sections. Rare words count more.
def _idf(doc_count: int, docs_with_word: int) -> float:
    return math.log(1 + (doc_count - docs_with_word + 0.5) / (docs_with_word + 0.5))


# Read one FAQ file and remember its word counts. Later calls reuse this.
def load_index(name: str) -> dict[str, Any] | None:
    safe = _safe_name(name)
    if safe is None:
        return None
    cached = _INDEXES.get(safe)
    if cached is not None:
        return cached
    path = kb_file(safe)
    if path is None:
        return None
    sections = _sections(path.read_text(encoding="utf-8"))
    if not sections:
        return None
    prepared: list[dict[str, Any]] = []
    doc_frequency: dict[str, int] = {}
    total_length = 0
    for section in sections:
        words = _tokens(f"{section['title']} {section['text']}")
        counts: dict[str, int] = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        for word in counts:
            doc_frequency[word] = doc_frequency.get(word, 0) + 1
        total_length += len(words)
        prepared.append(
            {
                "title": section["title"],
                "text": section["text"],
                "counts": counts,
                "length": len(words),
            }
        )
    index = {
        "sections": prepared,
        "doc_frequency": doc_frequency,
        "average_length": total_length / len(prepared),
    }
    _INDEXES[safe] = index
    return index


# Score each section with BM25 and return the best ones, or nothing if the match is weak.
def search(question: str, top_k: int = 2, kb_name: str = "clinic-faq") -> list[dict[str, Any]]:
    if top_k < 1:
        return []
    index = load_index(kb_name)
    if index is None:
        return []
    query = _tokens(question)
    if not query:
        return []
    sections: list[dict[str, Any]] = index["sections"]
    doc_count = len(sections)
    average_length = float(index["average_length"]) or 1.0
    doc_frequency: dict[str, int] = index["doc_frequency"]
    ranked: list[dict[str, Any]] = []
    for section in sections:
        counts: dict[str, int] = section["counts"]
        length = int(section["length"])
        score = 0.0
        for word in set(query):
            frequency = counts.get(word, 0)
            if frequency == 0:
                continue
            idf = _idf(doc_count, doc_frequency.get(word, 0))
            normal = 1 - _B + _B * (length / average_length)
            score += idf * (frequency * (_K1 + 1)) / (frequency + _K1 * normal)
        if score <= 0:
            continue
        ranked.append(
            {
                "title": section["title"],
                "text": section["text"],
                "score": round(score, 3),
            }
        )
    ranked.sort(key=lambda item: float(item["score"]), reverse=True)
    if not ranked or float(ranked[0]["score"]) < _SCORE_MIN:
        return []
    return [item for item in ranked[:top_k] if float(item["score"]) >= _SCORE_MIN]


# Load the sample FAQ when the agent process starts.
load_index("clinic-faq")
