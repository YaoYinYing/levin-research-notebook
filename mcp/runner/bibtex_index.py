"""BibTeX literature index (bibtexparser v2).

Metadata hygiene follows the EndNoteTweak conventions
(https://github.com/YaoYinYing/EndnoteTweak): prefer a DOI, fall back to the title, keep whatever
annotation the export carried, and record what is missing instead of presenting messy metadata as
if it were clean. Nothing is copied or fetched here — the plugin only reads a .bib that already
exists in the workspace.
"""
from __future__ import annotations

import re
from pathlib import Path

MAX_ENTRIES = 2000

# EndNote/Zotero exports spread the useful annotation over several fields.
ANNOTATION_FIELDS = ("note", "annote", "abstract", "keywords", "file")
_SUSPECT = re.compile(r"^\s*(todo|tbd|unknown|n/?a|\?+)\s*$", re.I)


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _authors(raw: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s+and\s+", raw) if part.strip()]
    names = []
    for part in parts:
        if "," in part:
            last, first = [x.strip() for x in part.split(",", 1)]
            names.append(f"{first} {last}".strip())
        else:
            names.append(part)
    return names


def _short_authors(names: list[str]) -> str:
    if not names:
        return "Unknown"
    if len(names) == 1:
        return names[0].split()[-1] if names[0].split() else names[0]
    if len(names) == 2:
        return f"{names[0].split()[-1]} & {names[1].split()[-1]}"
    return f"{names[0].split()[-1]} et al."


def _issues(entry: dict) -> list[str]:
    """What a reader must not trust yet, rather than silently accepting it."""
    out = []
    if not entry["title"] or _SUSPECT.match(entry["title"]):
        out.append("缺标题")
    if not entry["year"]:
        out.append("缺年份")
    if not entry["doi"]:
        out.append("缺 DOI")
    if not entry["venue"]:
        out.append("缺期刊/会议")
    if not entry["authors"]:
        out.append("缺作者")
    return out


def parse_bibtex(text: str, source: str = "inline") -> tuple[list[dict], list[str]]:
    """Return normalized reference records plus parse warnings."""
    import bibtexparser

    library = bibtexparser.parse_string(text)
    warnings = [f"无法解析的块 {index + 1}: {block}" for index, block in enumerate(getattr(library, "failed_blocks", []))]
    records = []
    for entry in list(library.entries)[:MAX_ENTRIES]:
        fields = {name: _text(field.value) for name, field in entry.fields_dict.items()}
        authors = _authors(fields.get("author", ""))
        year = fields.get("year", "")
        year_value = int(year) if year.isdigit() else None
        record = {
            "id": _text(entry.key),
            "entry_type": _text(entry.entry_type).lower(),
            "title": fields.get("title", ""),
            "authors": authors,
            "year": year_value,
            "venue": fields.get("journal") or fields.get("booktitle") or fields.get("publisher", ""),
            "doi": fields.get("doi", ""),
            "citation": "",
            "key_findings": "",
            "source": source,
        }
        for name in ANNOTATION_FIELDS:
            if fields.get(name):
                record["key_findings"] = fields[name]
                break
        citation = f"{_short_authors(authors)} {year_value or 'n.d.'}"
        if record["title"]:
            citation += f", {record['title'][:80]}"
        record["citation"] = citation
        record["metadata_issues"] = _issues(record)
        records.append(record)
    if len(library.entries) > MAX_ENTRIES:
        warnings.append(f"仅解析前 {MAX_ENTRIES} 条文献")
    return records, warnings


def read_bibtex(source: str, workspace: Path) -> tuple[list[dict], list[str], str]:
    """Resolve inline BibTeX or a workspace-relative .bib path."""
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = workspace / source
    if candidate.suffix.lower() in (".bib", ".bibtex") and candidate.is_file():
        return (*parse_bibtex(candidate.read_text(encoding="utf-8", errors="replace"), source=str(candidate)),
                str(candidate))
    if source.lstrip().startswith("@"):
        return (*parse_bibtex(source, source="inline"), "inline")
    raise ValueError(f"bibtex source is neither an existing .bib file nor inline BibTeX: {source}")


# Recomputed from the merged record, never taken from an explicit override: these describe
# the metadata itself, so a stale copy would contradict the fields printed beside it.
DERIVED_FIELDS = ("metadata_issues",)


def merge(explicit: list[dict], parsed: list[dict]) -> list[dict]:
    """Explicit records win field by field; parsed metadata fills the gaps."""
    by_id = {record["id"]: dict(record) for record in parsed if record.get("id")}
    order = [record["id"] for record in parsed if record.get("id")]
    for record in explicit:
        key = record.get("id")
        if not key:
            continue
        if key in by_id:
            for name, value in record.items():
                if name in DERIVED_FIELDS:
                    continue
                if value not in (None, "", []):
                    by_id[key][name] = value
        else:
            by_id[key] = {name: value for name, value in record.items() if name not in DERIVED_FIELDS}
            order.append(key)
    merged = [by_id[key] for key in order]
    for record in merged:
        if record.get("source"):
            record["metadata_issues"] = _issues(record)
    return merged
