#!/usr/bin/env python3
"""Phase 1.6 — static voice/content hygiene audit across lens-demo.

Companion to voice_audit.py (which scans Stage 1 card JSON outputs). This script
scans the static source files that ship with the demo — index.html seed content,
worker.js prompt templates and comments, and the data/*.md prompt-bundle files —
for violations of the same locked rules the live model is held to:

  - Invariant 4  : em dashes (—) banned in all active source files
  - Invariant 10 : "Claude" references banned in data/*.md (prompt bundle)
  - Invariant 11 : verdict words banned in seed card/chat content
  - Voice Brief  : "against" as comparison connector banned on cards
  - Voice Brief  : jargon ban (RBAC, "pulled forward", "over-indexed", etc.)
  - Banned phrases blocklist from voice-brief.md Ground Rules

Emits a single structured catalog to scripts/eval/static_voice_audit_report.json
so the fix pass can work from one source of truth.

Rule sources:
  - data/voice-brief.md Section 3 (Voice Spine, locked 2026-04-24)
  - tests/content-hygiene.test.js (Invariants 4, 5, 7, 9, 10, 11)
  - nomocoda-operating-context skill v11
  - Asana 1214272412203471 (Phase 1.6 handoff)
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_PATH = Path(__file__).resolve().parent / "static_voice_audit_report.json"

# Files in scope. marketing-leader-brief.md is loaded into worker.js:23 but is
# missing from ACTIVE_FILES in content-hygiene.test.js — include it here so
# Phase 1.6 closes that gap too.
SCAN_FILES = [
    "index.html",
    "worker.js",
    "data/persona.md",
    "data/voice-brief.md",
    "data/atlas-saas.md",
    "data/marketing-leader-brief.md",
]

# Seed card/chat content in index.html is extracted with this pattern (mirrors
# content-hygiene.test.js). Violations inside these string values are more
# severe than the same violation in a comment — a prospect sees them rendered.
SEED_FIELD_PATTERN = re.compile(
    r"(headline|body|content)\s*:\s*'((?:\\.|[^'\\])*)'"
)

EM_DASH_PATTERN = re.compile(r"\u2014")
AGAINST_PATTERN = re.compile(r"\bagainst\b", re.IGNORECASE)
CLAUDE_PATTERN = re.compile(r"\bclaude\b", re.IGNORECASE)

BANNED_PHRASES = [
    "leverage synergies",
    "impactful",
    "holistic",
    "thought leadership",
    "best-in-class",
    "best in class",
    "next-gen",
    "next gen",
    "crush it",
    "unlock value",
    "360-degree view",
    "360 degree view",
]

INSIDER_JARGON = [
    "pulled forward",
    "over-indexed",
    "over indexed",
    "operationalized",
    "RBAC",
]

# Subset of Invariant 11 verdict words. Kept aligned with content-hygiene.test.js.
VERDICT_WORDS = [
    ("gap", re.compile(r"\bgap(s)?\b", re.IGNORECASE)),
    ("worsened", re.compile(r"\bworsened\b", re.IGNORECASE)),
    ("deteriorated", re.compile(r"\bdeteriorated\b", re.IGNORECASE)),
    ("declined", re.compile(r"\bdeclined?\b", re.IGNORECASE)),
    ("dropped", re.compile(r"\bdropped\b", re.IGNORECASE)),
    ("stretched", re.compile(r"\bstretched\b", re.IGNORECASE)),
    ("ballooned", re.compile(r"\bballooned\b", re.IGNORECASE)),
    ("softened", re.compile(r"\bsoftened\b", re.IGNORECASE)),
    ("weakened", re.compile(r"\bweakened\b", re.IGNORECASE)),
    ("weaker", re.compile(r"\bweaker\b", re.IGNORECASE)),
    ("widened", re.compile(r"\bwidened\b", re.IGNORECASE)),
    ("shortfall", re.compile(r"\bshortfall\b", re.IGNORECASE)),
    ("concerning", re.compile(r"\bconcerning\b", re.IGNORECASE)),
    ("shy of", re.compile(r"\bshy of\b", re.IGNORECASE)),
    ("short of", re.compile(r"\bshort of\b", re.IGNORECASE)),
    ("fell to/from/short", re.compile(r"\bfell (to|from|short)\b", re.IGNORECASE)),
    ("down to/from", re.compile(r"\bdown (to|from)\b", re.IGNORECASE)),
    ("lower than", re.compile(r"\blower than\b", re.IGNORECASE)),
    ("wider than", re.compile(r"\bwider than\b", re.IGNORECASE)),
    ("missed", re.compile(r"\bmissed\b", re.IGNORECASE)),
    ("behind", re.compile(r"\bbehind\b", re.IGNORECASE)),
    ("below", re.compile(r"\bbelow\b", re.IGNORECASE)),
    ("implementation gap", re.compile(r"\bimplementation gap\b", re.IGNORECASE)),
]


def line_col(content: str, index: int) -> tuple[int, int]:
    line = content.count("\n", 0, index) + 1
    last_nl = content.rfind("\n", 0, index)
    col = index - last_nl if last_nl >= 0 else index + 1
    return line, col


def snippet(content: str, start: int, end: int, radius: int = 50) -> str:
    left = max(0, start - radius)
    right = min(len(content), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(content) else ""
    return f"{prefix}{content[left:right]}{suffix}".replace("\n", " ")


def find_all(pattern: re.Pattern, content: str):
    for m in pattern.finditer(content):
        yield m.start(), m.end(), m.group(0)


def extract_seed_spans(content: str) -> list[tuple[int, int, str, str]]:
    """Return (start, end, field, value) for each headline/body/content string."""
    spans = []
    for m in SEED_FIELD_PATTERN.finditer(content):
        # Value span is the capture group 2 within the match.
        value_start = m.start(2)
        value_end = m.end(2)
        spans.append((value_start, value_end, m.group(1), m.group(2)))
    return spans


def record(violations, *, path, category, severity, subcategory, content, start, end, match, surface):
    line, col = line_col(content, start)
    violations.append({
        "file": path,
        "line": line,
        "col": col,
        "severity": severity,
        "category": category,
        "subcategory": subcategory,
        "match": match,
        "surface": surface,  # "seed" | "template" | "comment" | "doc"
        "snippet": snippet(content, start, end),
    })


def classify_surface(path: str, content: str, index: int, seed_spans) -> str:
    if path == "index.html":
        for vs, ve, _field, _value in seed_spans:
            if vs <= index < ve:
                return "seed"
        return "template"
    if path == "worker.js":
        return "template"
    if path.startswith("data/"):
        return "doc"
    return "template"


def scan_file(path: str, violations: list) -> None:
    full_path = REPO_ROOT / path
    content = full_path.read_text(encoding="utf-8")
    seed_spans = extract_seed_spans(content) if path == "index.html" else []

    # Em dashes — hard, all files.
    for s, e, m in find_all(EM_DASH_PATTERN, content):
        record(
            violations,
            path=path,
            category="em_dash",
            severity="hard",
            subcategory="em_dash",
            content=content,
            start=s,
            end=e,
            match=m,
            surface=classify_surface(path, content, s, seed_spans),
        )

    # "against" — hard, but surface-sensitive. On seed card values and in
    # data/*.md it's always a voice violation; in worker.js prompt templates
    # that TEACH the rule it's intentional and shouldn't be flagged. We report
    # everything and let the fix pass triage template-prose occurrences.
    for s, e, m in find_all(AGAINST_PATTERN, content):
        record(
            violations,
            path=path,
            category="against_as_comparison",
            severity="hard",
            subcategory="against",
            content=content,
            start=s,
            end=e,
            match=m,
            surface=classify_surface(path, content, s, seed_spans),
        )

    # "Claude" — hard inside data/*.md only (Invariant 10).
    if path.startswith("data/"):
        for s, e, m in find_all(CLAUDE_PATTERN, content):
            record(
                violations,
                path=path,
                category="claude_reference",
                severity="hard",
                subcategory="claude",
                content=content,
                start=s,
                end=e,
                match=m,
                surface="doc",
            )

    # Banned phrases — hard.
    for phrase in BANNED_PHRASES:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        for s, e, m in find_all(pattern, content):
            record(
                violations,
                path=path,
                category="banned_phrase",
                severity="hard",
                subcategory=phrase,
                content=content,
                start=s,
                end=e,
                match=m,
                surface=classify_surface(path, content, s, seed_spans),
            )

    # Insider jargon — soft in prompts/comments, hard on seed content.
    for word in INSIDER_JARGON:
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        for s, e, m in find_all(pattern, content):
            surface = classify_surface(path, content, s, seed_spans)
            severity = "hard" if surface == "seed" else "soft"
            record(
                violations,
                path=path,
                category="insider_jargon",
                severity=severity,
                subcategory=word,
                content=content,
                start=s,
                end=e,
                match=m,
                surface=surface,
            )

    # Verdict words — only hard when they appear inside a seed string value.
    # Same word elsewhere in worker.js prompt prose is often naming the rule.
    for path_key, pattern in [(w, p) for w, p in VERDICT_WORDS]:
        pass
    for word, pattern in VERDICT_WORDS:
        for s, e, m in find_all(pattern, content):
            surface = classify_surface(path, content, s, seed_spans)
            # Only flag verdict words inside seed values on index.html, or in
            # data/*.md files (prompt bundle prose that the model reads).
            if path == "index.html" and surface != "seed":
                continue
            if path == "worker.js":
                continue  # worker prose often names the rules themselves
            record(
                violations,
                path=path,
                category="verdict_word",
                severity="hard",
                subcategory=word,
                content=content,
                start=s,
                end=e,
                match=m,
                surface=surface,
            )


def build_report() -> dict:
    violations: list = []
    for path in SCAN_FILES:
        scan_file(path, violations)

    totals_by_file = Counter(v["file"] for v in violations)
    totals_by_category = Counter(v["category"] for v in violations)
    totals_by_severity = Counter(v["severity"] for v in violations)
    totals_by_surface = Counter(v["surface"] for v in violations)

    per_file_category: dict[str, Counter] = defaultdict(Counter)
    for v in violations:
        per_file_category[v["file"]][v["category"]] += 1

    return {
        "files_scanned": SCAN_FILES,
        "totals": {
            "violations_total": len(violations),
            "by_file": dict(totals_by_file),
            "by_category": dict(totals_by_category),
            "by_severity": dict(totals_by_severity),
            "by_surface": dict(totals_by_surface),
        },
        "per_file_breakdown": {
            f: dict(c) for f, c in per_file_category.items()
        },
        "violations": violations,
    }


def format_summary(report: dict) -> str:
    t = report["totals"]
    lines = [
        f"Files scanned: {len(report['files_scanned'])}",
        f"Total violations: {t['violations_total']} "
        f"(hard={t['by_severity'].get('hard', 0)}, soft={t['by_severity'].get('soft', 0)})",
        "",
        "By file:",
    ]
    for f, n in sorted(t["by_file"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {f}: {n}")
    lines.append("")
    lines.append("By category:")
    for cat, n in sorted(t["by_category"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {cat}: {n}")
    lines.append("")
    lines.append("By surface (seed = rendered to users, template/doc = prompt bundle):")
    for s, n in sorted(t["by_surface"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {s}: {n}")
    return "\n".join(lines)


def main() -> None:
    from datetime import datetime, timezone

    report = build_report()
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(format_summary(report))
    print(f"\nReport written to {REPORT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
