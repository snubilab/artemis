"""Eligibility segmentation: one LLM step marks where the criteria are, and code slices.

RFC-016 §5. Before this step, which part of a document was its inclusion or exclusion
section, and where one criterion ended and the next began, was decided by heading and
terminator vocabularies, a sponsor-name header filter, bullet and comma splitting, a
superscript-rejoin rule and an ``[OR-GROUP]`` collapse keyed on quantifier phrases
(inventory rows S1-S8 and A6). Each of those read protocol language to decide what it
meant. Now the model decides it, and quotes the text that shows it.

For each part of the document the model returns, per section kind (inclusion,
exclusion): the fragment where the section starts and where it ends, the starting and
ending fragment of every criterion that begins in the part, and the full lines inside
the section that are page layout rather than criterion text. Code checks one thing --
that each fragment occurs in the text (whitespace-tolerant, case-insensitive) -- and
slices by it. A fragment that does not occur is not used, and the part of the text it
was meant to mark is not cut there; the rejection is recorded in
:attr:`Segmentation.rejected` and announced by every caller. There is no fallback to a
rule: a part whose call fails contributes nothing.

Positional choices made here read no words: fragments are searched in the order the
model listed them, a section starts at the last occurrence of its start fragment before
its first criterion, and when a document states the same list twice the first statement
is used and the second is recorded as unused (``outside-the-section``).

Long documents are sent in overlapping parts (:func:`split_into_chunks`) so that every
call stays well inside the serving context; fragments are mapped back to document
offsets, so a criterion seen by two parts is one criterion.

Cache: one JSONL file keyed on the prompt version, the system prompt, the rendered part
and the resolved model. ``ARTEMIS_SEGMENTATION_CACHE_PATH`` moves it,
``ARTEMIS_SEGMENTATION_CACHE=0`` disables it. Failed calls are never cached.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.span_match import fold, is_space

logger = logging.getLogger(__name__)

#: Bumped whenever a prompt below changes meaning; part of the cache key.
SEGMENTATION_PROMPT_VERSION = "rfc016-s5-v2"  # v2: answer constrained by ANSWER_SCHEMA

#: Characters per part, and how many of them the next part repeats. A part of this size
#: is roughly 12-14k tokens, well inside the 65,536-token serving context with room for
#: the answer; the overlap is wider than any single criterion in the six-trial corpus, so
#: a criterion cut by one part's edge is seen whole by the next.
PART_CHARS = 48_000
PART_OVERLAP = 8_000

#: Upper bound on one answer, so a generation that stops producing content cannot run to
#: the context ceiling. A part of the largest corpus section needs well under half of it.
MAX_ANSWER_TOKENS = 4096

#: Caps on `interruptions`, the one field whose length the document does not bound: live,
#: it ran to whole copied pages and one entry per page number. A line past the cap is not
#: a full line and is rejected, which only leaves it in the criterion text.
INTERRUPTIONS_MAX = 16
INTERRUPTION_LINE_CHARS = 160


class SectionKind(str, Enum):
    """The two sections the step marks; the values are the JSON keys of the answer."""

    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


FIELD_START = "start"
FIELD_END = "end"
FIELD_ITEMS = "items"
FIELD_INTERRUPTIONS = "interruptions"
#: Rejection field names for a criterion's own fragments, and for the answer as a whole.
FIELD_ITEM_START = "items.start"
FIELD_ITEM_END = "items.end"
FIELD_ANSWER = "*"

REASON_NOT_FOUND = "not-a-substring-of-the-text"
#: The document contains the fragment, but not where the answer's own order puts it.
REASON_MISPLACED = "not-where-the-answer-places-it"
REASON_OUTSIDE_SECTION = "outside-the-section"
REASON_INVALID = "not-the-requested-object"
REASON_CALL_FAILED = "call-failed"
REASON_UNMARKED = "never-marked"
REASON_EMPTY = "empty-after-interruptions"
REASON_UNBOUNDED = "no-verified-end"


SEGMENTATION_SYSTEM_PROMPT = """You mark where the eligibility criteria of a clinical trial \
are written in a document, by copying fragments of its text.

Every fragment you return is copied from the text character for character: no paraphrase, \
no corrected spelling or symbol, no expanded abbreviation, no added or removed word. A line \
break inside a fragment may be written as a single space. A fragment that does not occur in \
the text is discarded, and the part of the text it was meant to mark is not used.

Return one JSON object and nothing else."""

SEGMENTATION_PROMPT = """Text (part {part} of {parts} of the document):
<<<
{text}
>>>

The inclusion criteria are the conditions a patient must meet to enter the trial. The \
exclusion criteria are the conditions that keep a patient out of it. Report each kind as a \
section: the stretch of this text that states those criteria, as a list or as running text. \
An entry in a table of contents, a reference to another place and a sentence that only \
mentions the criteria are not a section. Lines of the page layout that interrupt a section \
do not end it. When this part holds more than one statement of the same kind's criteria, \
report the first.

For each kind, return an object with the fields below, or null when this part of the \
document holds none of that kind's criteria.

`start` is the first characters of the section: its heading when it has one, otherwise the \
beginning of its first criterion. It is null when the section began before this part of the \
document.

`end` is the last characters of the section's last criterion. It is null when the section \
continues past this part of the document.

`items` lists, in the order they appear, the criteria of the section that begin in this part \
of the document. A criterion is one entry of the section's top-level list together with \
every sub-item listed under it; in running text, a criterion is one condition the text \
states. For each criterion, `start` is its first characters after the number or bullet that \
marks it, and `end` is its last characters; `end` is null when the criterion continues past \
this part of the document.

`interruptions` lists, once each, every full line inside the section that belongs to the \
page layout rather than to any criterion: running headers, running footers and page numbers. \
It is an empty list when there are none.

Copy enough characters for each `start` and `end` that the fragment occurs only once between \
the places it separates, and no more than that needs.

Output JSON:
{{"inclusion": {{"start": "<fragment, or null>", "end": "<fragment, or null>", \
"items": [{{"start": "<fragment>", "end": "<fragment, or null>"}}], \
"interruptions": ["<full line>"]}}, \
"exclusion": {{"start": "<fragment, or null>", "end": "<fragment, or null>", \
"items": [{{"start": "<fragment>", "end": "<fragment, or null>"}}], \
"interruptions": ["<full line>"]}}}}"""


_NULL = {"type": "null"}
_FRAGMENT = {"anyOf": [{"type": "string"}, _NULL]}
_SECTION = {
    "anyOf": [
        _NULL,
        {
            "type": "object",
            "additionalProperties": False,
            "required": [FIELD_START, FIELD_END, FIELD_ITEMS, FIELD_INTERRUPTIONS],
            "properties": {
                FIELD_START: _FRAGMENT,
                FIELD_END: _FRAGMENT,
                # No length cap on a fragment: a capped `end` is a prefix and marks an
                # earlier end than the model quoted.
                FIELD_ITEMS: {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [FIELD_START, FIELD_END],
                        "properties": {FIELD_START: {"type": "string"}, FIELD_END: _FRAGMENT},
                    },
                },
                FIELD_INTERRUPTIONS: {
                    "type": "array",
                    "maxItems": INTERRUPTIONS_MAX,
                    "items": {"type": "string", "maxLength": INTERRUPTION_LINE_CHARS},
                },
            },
        },
    ]
}
#: The answer's shape, enforced by the server's structured output. Under plain json_object
#: the P6 smoke lost 8 of 36 parts at the answer budget: a malformed key followed by
#: whitespace to the ceiling, invented fields, or `interruptions` copying whole pages.
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [kind.value for kind in SectionKind],
    "properties": {kind.value: _SECTION for kind in SectionKind},
}


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Chunk:
    """One part of the document as the model sees it.

    :param index: 0-based position of the part.
    :param count: how many parts the document was split into.
    :param offset: character offset of the part in the document.
    :param text: the part's text, an exact slice of the document.
    """

    index: int
    count: int
    offset: int
    text: str


@dataclass(frozen=True)
class Rejection:
    """A fragment the step did not use, and why.

    :param kind: ``inclusion``, ``exclusion``, or ``*`` for a whole answer.
    :param field: which fragment (``start``, ``end``, ``items.start``, ``items.end``,
        ``interruptions``, ``*``).
    :param fragment: what the model returned, or the error for a failed call.
    :param reason: one of the ``REASON_*`` constants.
    :param part: 0-based index of the part the fragment came from.
    """

    kind: str
    field: str
    fragment: Any
    reason: str
    part: int


@dataclass
class Segmentation:
    """The criteria of one document, and every fragment that was not used."""

    items: dict[str, list[str]]
    rejected: list[Rejection] = field(default_factory=list)
    parts: int = 0
    #: per kind, the offset of the section's start and of its end (the end of the text
    #: when no end was verified), for the kinds that yielded criteria
    sections: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: the offsets of every part whose call failed or whose answer was unreadable
    failed_parts: list[tuple[int, int]] = field(default_factory=list)

    def criteria(self) -> dict[str, list[str]]:
        """:returns: criterion texts per section kind, in document order."""
        return {kind.value: list(self.items.get(kind.value) or []) for kind in SectionKind}

    def unsettled(self, kind: str) -> bool:
        """Whether a part that failed could have held this section.

        The section is the first statement of the list the parts reported. A failed part
        starting before the section's end may have held an earlier statement, or the
        rest of this one, so which stretch is the section was not verified.

        :param kind: ``inclusion`` or ``exclusion``.
        :returns: True when the kind yielded a section and a failed part starts before
            its end.
        """
        section = self.sections.get(kind)
        return section is not None and any(lo < section[1] for lo, _hi in self.failed_parts)

    @property
    def failures(self) -> list[Rejection]:
        """Rejections that mean a fragment or a call failed (not merely unused)."""
        return [r for r in self.rejected if r.reason != REASON_OUTSIDE_SECTION]

    @property
    def unused(self) -> list[Rejection]:
        """Verified fragments of a second statement of a list, recorded and not used."""
        return [r for r in self.rejected if r.reason == REASON_OUTSIDE_SECTION]

    def describe_rejections(
        self, rejections: Sequence[Rejection] | None = None, limit: int = 8
    ) -> str:
        """One line for a run log.

        :param rejections: which ones to describe; all of them when None.
        :param limit: how many to spell out before summarising the rest.
        :returns: the count, then ``kind field reason: fragment (part n)`` for each.
        """
        chosen = list(self.rejected if rejections is None else rejections)
        shown = []
        for rejection in chosen[:limit]:
            preview = " ".join(str(rejection.fragment).split())[:80]
            where = f" (part {rejection.part + 1})" if rejection.part >= 0 else ""
            shown.append(
                f"{rejection.kind} {rejection.field} {rejection.reason}: {preview!r}{where}"
            )
        more = f"; and {len(chosen) - limit} more" if len(chosen) > limit else ""
        return f"{len(chosen)} fragment(s) not used: " + "; ".join(shown) + more


# --------------------------------------------------------------------------- #
# The one text check: a fragment occurs in the text
# --------------------------------------------------------------------------- #


# The comparison form (:func:`src.utils.span_match.fold`) is shared with every other span
# check in the pipeline, so a fragment located here verifies there too.


def _one_line(text: str) -> str:
    """A criterion as one line: :func:`src.utils.span_match.is_space` runs become one space."""
    spaced = "".join(" " if is_space(char) else char for char in text)
    return " ".join(spaced.split())


class _Located:
    """The document in comparison form, searched by original offsets."""

    def __init__(self, text: str) -> None:
        self.form, self.index = fold(text)
        self.length = len(text)

    def _at(self, offset: int) -> int:
        return bisect.bisect_left(self.index, offset)

    def _span(self, k: int, probe: str) -> tuple[int, int]:
        return self.index[k], self.index[k + len(probe) - 1] + 1

    def find(self, fragment: Any, lo: int, hi: int) -> tuple[int, int] | None:
        """First occurrence of ``fragment`` lying within ``[lo, hi)``, as original offsets."""
        if not isinstance(fragment, str):
            return None
        probe = fold(fragment)[0]
        if not probe:
            return None
        k = self.form.find(probe, self._at(lo), self._at(hi))
        return self._span(k, probe) if k >= 0 else None

    def absent_reason(self, fragment: Any) -> str:
        """Why a fragment was not found where it was looked for: misplaced when the
        document holds it elsewhere, else not in the text."""
        return REASON_NOT_FOUND if self.find(fragment, 0, self.length) is None else REASON_MISPLACED

    def find_last(self, fragment: Any, lo: int, hi: int) -> tuple[int, int] | None:
        """Last occurrence of ``fragment`` lying within ``[lo, hi)``."""
        if not isinstance(fragment, str):
            return None
        probe = fold(fragment)[0]
        if not probe:
            return None
        k = self.form.rfind(probe, self._at(lo), self._at(hi))
        return self._span(k, probe) if k >= 0 else None

    def find_last_starting_by(
        self, fragment: Any, lo: int, latest_start: int
    ) -> tuple[int, int] | None:
        """Last occurrence of ``fragment`` at or after ``lo`` that starts no later than
        ``latest_start`` (it may run past it)."""
        if not isinstance(fragment, str):
            return None
        probe = fold(fragment)[0]
        if not probe:
            return None
        k = self.form.rfind(probe, self._at(lo), self._at(latest_start) + len(probe))
        return self._span(k, probe) if k >= 0 else None


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def split_into_chunks(
    text: str, size: int = PART_CHARS, overlap: int = PART_OVERLAP
) -> list[Chunk]:
    """Split ``text`` into overlapping parts that together cover it.

    Each part ends at a line break when one falls in its second half, and the next part
    starts at the beginning of the line ``overlap`` characters before that end.

    :param text: the document.
    :param size: the most characters one part holds.
    :param overlap: how many characters consecutive parts share, at least.
    :returns: the parts in order; empty when the text holds no visible character.
    """
    if not text.strip():
        return []
    bounds: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut > start:
                end = cut + 1
        bounds.append((start, end))
        if end >= len(text):
            break
        back = max(end - overlap, start + 1)
        line_start = text.rfind("\n", start, back) + 1
        start = line_start if line_start > start else back
    return [Chunk(i, len(bounds), lo, text[lo:hi]) for i, (lo, hi) in enumerate(bounds)]


# --------------------------------------------------------------------------- #
# Reading one answer
# --------------------------------------------------------------------------- #


@dataclass
class _Marks:
    """Every verified fragment of one section kind, in document offsets."""

    starts: list[tuple[int, Any, int, bool]] = field(default_factory=list)
    ends: list[tuple[int, Any, int]] = field(default_factory=list)
    #: criterion start offset -> [end offset or None, start fragment, part,
    #: whether any part offered an end fragment for it]
    items: dict[int, list[Any]] = field(default_factory=dict)
    interruptions: set[str] = field(default_factory=set)
    end_offered: bool = False
    #: criterion start offset -> every part that listed it
    listed: dict[int, set[int]] = field(default_factory=dict)


def _read_section(
    located: _Located,
    chunk: Chunk,
    kind: str,
    section: Mapping[str, Any],
    marks: _Marks,
    rejected: list[Rejection],
) -> None:
    """Verify one part's answer for one section kind and add what holds to ``marks``."""
    lo, hi = chunk.offset, chunk.offset + len(chunk.text)

    def reject(name: str, fragment: Any, reason: str) -> None:
        rejected.append(Rejection(kind, name, fragment, reason, chunk.index))

    entries = section.get(FIELD_ITEMS)
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        reject(FIELD_ITEMS, entries, REASON_INVALID)
        entries = []

    # Criterion starts, in the order listed.
    heads: list[tuple[tuple[int, int], Any, Any]] = []
    cursor = lo
    for entry in entries:
        head_fragment = entry.get(FIELD_START) if isinstance(entry, Mapping) else None
        if not isinstance(head_fragment, str):
            reject(FIELD_ITEM_START, entry, REASON_INVALID)
            continue
        head = located.find(head_fragment, cursor, hi)
        if head is None:
            reject(FIELD_ITEM_START, head_fragment, located.absent_reason(head_fragment))
            continue
        heads.append((head, head_fragment, entry.get(FIELD_END)))
        cursor = head[1]

    # Criterion ends: between its start and the next criterion's start, the last
    # occurrence (a short fragment can recur inside the criterion); for the part's last
    # criterion there is no next start, so the first occurrence after its own.
    for position, (head, head_fragment, tail_fragment) in enumerate(heads):
        tail_end = None
        if tail_fragment is not None:
            if position + 1 < len(heads):
                tail = located.find_last(tail_fragment, head[0], heads[position + 1][0][0])
            else:
                tail = located.find(tail_fragment, head[0], hi)
            if tail is None:
                reject(FIELD_ITEM_END, tail_fragment, located.absent_reason(tail_fragment))
            else:
                tail_end = tail[1]
        marks.listed.setdefault(head[0], set()).add(chunk.index)
        known = marks.items.get(head[0])
        if known is None:
            marks.items[head[0]] = [tail_end, head_fragment, chunk.index, tail_fragment is not None]
        else:
            if known[0] is None and tail_end is not None:
                known[0] = tail_end
            known[3] = known[3] or tail_fragment is not None

    start_fragment = section.get(FIELD_START)
    section_start = None
    if start_fragment is not None:
        if heads:
            found = located.find_last_starting_by(start_fragment, lo, heads[0][0][0])
        else:
            found = located.find(start_fragment, lo, hi)
        if found is None:
            reject(FIELD_START, start_fragment, located.absent_reason(start_fragment))
        else:
            section_start = found[0]
            marks.starts.append((found[0], start_fragment, chunk.index, bool(heads)))

    end_fragment = section.get(FIELD_END)
    if end_fragment is not None:
        marks.end_offered = True
        # After the last criterion; failing that, after the first -- a criterion the
        # model listed past the section's end must not hide the end it also quoted.
        if heads:
            anchors = [heads[-1][0][0], heads[0][0][0]]
        else:
            anchors = [section_start if section_start is not None else lo]
        found = None
        for after in anchors:
            found = located.find(end_fragment, after, hi)
            if found is not None:
                break
        if found is None:
            reject(FIELD_END, end_fragment, located.absent_reason(end_fragment))
        else:
            marks.ends.append((found[1], end_fragment, chunk.index))

    lines = {fold(line)[0] for line in chunk.text.split("\n")}
    interruptions = section.get(FIELD_INTERRUPTIONS) or []
    if not isinstance(interruptions, list):
        reject(FIELD_INTERRUPTIONS, interruptions, REASON_INVALID)
        interruptions = []
    for line in interruptions:
        probe = fold(line)[0] if isinstance(line, str) else ""
        if probe and probe in lines:
            marks.interruptions.add(probe)
        else:
            reject(FIELD_INTERRUPTIONS, line, REASON_NOT_FOUND)


# --------------------------------------------------------------------------- #
# Assembling the parts
# --------------------------------------------------------------------------- #


def _assemble_kind(
    text: str, kind: str, marks: _Marks, rejected: list[Rejection]
) -> tuple[list[str], tuple[int, int] | None]:
    """The criteria of one section kind from every part's verified fragments, and the
    section's start and end offsets (None when the kind yielded nothing)."""
    if not marks.items and not marks.starts:
        return [], None

    # A start reported in a part where no criterion was verified is used only when no
    # part pairs a start with criteria: it may be a table-of-contents line.
    anchored = [s for s in marks.starts if s[3]] or marks.starts
    if anchored:
        section_start = min(s[0] for s in anchored)
    else:
        section_start = min(marks.items)
        rejected.append(
            Rejection(kind, FIELD_START, None, REASON_UNMARKED, marks.items[section_start][2])
        )
    # A part that starts this section and lists a criterion before its own quoted end
    # vouches that the section runs at least that far; an end another part quoted before
    # it is that part's short view (it listed fewer criteria than the section holds).
    own_end = {s[2]: len(text) for s in marks.starts if s[0] == section_start}
    for offset, _fragment, part in marks.ends:
        if part in own_end and section_start < offset < own_end[part]:
            own_end[part] = offset
    reach = max(
        (
            o
            for o, parts in marks.listed.items()
            for part in parts & own_end.keys()
            if section_start <= o < own_end[part]
        ),
        default=section_start,
    )
    later_ends = sorted(e for e in marks.ends if e[0] > reach)
    section_end = later_ends[0][0] if later_ends else None
    if section_end is None and not marks.end_offered:
        rejected.append(Rejection(kind, FIELD_END, None, REASON_UNMARKED, -1))

    for offset, fragment, part, _has_items in marks.starts:
        if offset != section_start:
            rejected.append(Rejection(kind, FIELD_START, fragment, REASON_OUTSIDE_SECTION, part))
    for offset, fragment, part in marks.ends:
        if offset != section_end:
            rejected.append(Rejection(kind, FIELD_END, fragment, REASON_OUTSIDE_SECTION, part))

    limit = section_end if section_end is not None else len(text)
    used = []
    for offset in sorted(marks.items):
        tail_end, fragment, part, end_offered = marks.items[offset]
        if section_start <= offset < limit:
            used.append((offset, tail_end, part, end_offered))
        else:
            rejected.append(
                Rejection(kind, FIELD_ITEM_START, fragment, REASON_OUTSIDE_SECTION, part)
            )

    # Where every criterion starts the same distance into its line, that stretch is the
    # number or bullet marking it (the model quotes from after it), so it is cut from the
    # criterion before it. Offsets only: what the stretch says is not read.
    indents = [offset - (text.rfind("\n", 0, offset) + 1) for offset, *_ in used]
    marker = indents[0] if indents and min(indents) == max(indents) else 0

    criteria: list[str] = []
    for position, (offset, tail_end, part, end_offered) in enumerate(used):
        bound = used[position + 1][0] - marker if position + 1 < len(used) else limit
        if tail_end is None:
            if not end_offered:
                rejected.append(Rejection(kind, FIELD_ITEM_END, None, REASON_UNMARKED, part))
            if position + 1 == len(used) and section_end is None:
                # Nothing verified ends it: neither its own end, a next criterion, nor
                # the section's end. Cutting at the end of the part would emit an
                # arbitrary stretch of the document as one criterion.
                rejected.append(
                    Rejection(
                        kind, FIELD_ITEM_START, marks.items[offset][1], REASON_UNBOUNDED, part
                    )
                )
                continue
            tail_end = bound
        end = min(tail_end, bound)
        kept = [
            line
            for line in text[offset:end].split("\n")
            if fold(line)[0] not in marks.interruptions
        ]
        criterion = _one_line("\n".join(kept))
        if criterion:
            criteria.append(criterion)
        else:
            rejected.append(Rejection(kind, FIELD_ITEM_START, text[offset:end], REASON_EMPTY, part))
    return criteria, ((section_start, limit) if criteria else None)


def assemble(text: str, answers: Sequence[tuple[Chunk, Any, str | None]]) -> Segmentation:
    """Turn every part's answer into the document's criteria.

    :param text: the document the parts were cut from.
    :param answers: ``(part, parsed answer, error)`` per part; ``error`` is set when the
        call failed, and the answer is then ignored.
    :returns: the criteria per kind and every rejection.
    """
    located = _Located(text)
    rejected: list[Rejection] = []
    usable: list[tuple[Chunk, Mapping[str, Any]]] = []
    failed_parts: list[tuple[int, int]] = []
    for chunk, payload, error in answers:
        if error is not None or not isinstance(payload, Mapping):
            failed_parts.append((chunk.offset, chunk.offset + len(chunk.text)))
        if error is not None:
            rejected.append(
                Rejection(FIELD_ANSWER, FIELD_ANSWER, error, REASON_CALL_FAILED, chunk.index)
            )
        elif not isinstance(payload, Mapping):
            rejected.append(
                Rejection(FIELD_ANSWER, FIELD_ANSWER, payload, REASON_INVALID, chunk.index)
            )
        else:
            usable.append((chunk, payload))

    items: dict[str, list[str]] = {}
    sections: dict[str, tuple[int, int]] = {}
    for kind in SectionKind:
        marks = _Marks()
        for chunk, payload in usable:
            section = payload.get(kind.value)
            if section is None:
                continue
            if not isinstance(section, Mapping):
                rejected.append(
                    Rejection(kind.value, FIELD_ANSWER, section, REASON_INVALID, chunk.index)
                )
                continue
            _read_section(located, chunk, kind.value, section, marks, rejected)
        items[kind.value], span = _assemble_kind(text, kind.value, marks, rejected)
        if span is not None:
            sections[kind.value] = span
    return Segmentation(
        items=items,
        rejected=rejected,
        parts=len(answers),
        sections=sections,
        failed_parts=failed_parts,
    )


# --------------------------------------------------------------------------- #
# The model call and its cache
# --------------------------------------------------------------------------- #

_CACHE_PATH_ENV = "ARTEMIS_SEGMENTATION_CACHE_PATH"
_CACHE_ENABLED_ENV = "ARTEMIS_SEGMENTATION_CACHE"
_WORKERS_ENV = "ARTEMIS_SEGMENTATION_WORKERS"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_PATH = _REPO_ROOT / ".cache" / "segmentation" / "segments.jsonl"

_cache_lock = threading.Lock()
_memory: dict[str, Any] = {}
_loaded_from: str | None = None


def render_prompt(chunk: Chunk) -> str:
    """:param chunk: one part. :returns: the user message for it."""
    return SEGMENTATION_PROMPT.format(part=chunk.index + 1, parts=chunk.count, text=chunk.text)


def cache_key(prompt: str, model: str) -> str:
    """:param prompt: the rendered user message. :param model: the resolved model.
    :returns: a stable SHA-256 key."""
    payload = json.dumps(
        [SEGMENTATION_PROMPT_VERSION, SEGMENTATION_SYSTEM_PROMPT, prompt, model], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path() -> Path:
    raw = os.environ.get(_CACHE_PATH_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def _cache_enabled() -> bool:
    return os.environ.get(_CACHE_ENABLED_ENV) != "0"


def _load_cache() -> dict[str, Any]:
    """Read the cache once per process and path. Call under the lock."""
    global _loaded_from
    path = _cache_path()
    if _loaded_from == str(path):
        return _memory
    _memory.clear()
    _loaded_from = str(path)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    _memory[record["key"]] = record["payload"]
                except (ValueError, KeyError, TypeError):
                    logger.warning("[segmentation] skipping damaged cache line %s:%d", path, number)
    return _memory


def _cache_get(key: str) -> Any:
    if not _cache_enabled():
        return None
    with _cache_lock:
        return _load_cache().get(key)


def _cache_put(key: str, payload: Any, model: str) -> None:
    if not _cache_enabled():
        return
    with _cache_lock:
        _load_cache()[key] = payload
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "payload": payload,
            "model": model,
            "promptVersion": SEGMENTATION_PROMPT_VERSION,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def reset_cache_for_tests() -> None:
    """Drop the in-process cache. Test helper, not production API."""
    global _loaded_from
    with _cache_lock:
        _loaded_from = None
        _memory.clear()


def _build_llm(model: str) -> Any:
    """:param model: the resolved model. :returns: a chat model handle (separate so a
    test substitutes a stub without reaching a network)."""
    from src.utils.llm import get_llm

    return get_llm(
        model_name=model,
        temperature=0.0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "eligibility_segmentation",
                "schema": ANSWER_SCHEMA,
                "strict": True,
            },
        },
        max_tokens=MAX_ANSWER_TOKENS,
    )


def _complete(llm: Any, prompt: str) -> Any:
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.utils.llm import _last_json_value, extract_answer, raise_if_truncated

    response = llm.invoke(
        [SystemMessage(content=SEGMENTATION_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    raise_if_truncated(response, what="eligibility segmentation")
    cleaned, _strategy = extract_answer(str(response.content))
    try:
        return json.loads(cleaned)
    except ValueError:
        value = _last_json_value(cleaned)
        if value is None:
            raise
        return json.loads(value)


def _responder(model: str | None = None) -> Callable[[Chunk], Any]:
    """The production answer source: the cache, else the model.

    :param model: model override; defaults to the pipeline's resolved model.
    :returns: a function from a part to the parsed answer; it raises when the call fails.
    """
    from src.utils.llm import resolve_model

    resolved = resolve_model(model)
    holder: list[Any] = []
    lock = threading.Lock()

    def respond(chunk: Chunk) -> Any:
        prompt = render_prompt(chunk)
        key = cache_key(prompt, resolved)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        with lock:
            if not holder:
                holder.append(_build_llm(resolved))
        payload = _complete(holder[0], prompt)
        _cache_put(key, payload, resolved)
        return payload

    return respond


def _workers() -> int:
    raw = os.environ.get(_WORKERS_ENV, "").strip()
    return max(1, int(raw)) if raw else 4


def segment_eligibility(
    text: str,
    *,
    respond: Callable[[Chunk], Any] | None = None,
    model: str | None = None,
) -> Segmentation:
    """Find the inclusion and exclusion criteria of one document.

    :param text: the document as production reads it (a PDF's plain ``pdftotext``
        output, a registry record's eligibility text, a PMC body, an abstract).
    :param respond: answer source for one part; the cached model call when None.
    :param model: model override for the default answer source.
    :returns: the criteria per section kind and every fragment that was not used. A
        part whose call fails is recorded and contributes nothing.
    """
    chunks = split_into_chunks(text or "")
    if not chunks:
        return Segmentation(items={kind.value: [] for kind in SectionKind}, parts=0)
    answer = respond if respond is not None else _responder(model)

    def run(chunk: Chunk) -> tuple[Chunk, Any, str | None]:
        try:
            return chunk, answer(chunk), None
        except Exception as exc:  # recorded as a rejection; never replaced by a rule
            logger.warning(
                "[segmentation] part %d/%d failed: %s", chunk.index + 1, chunk.count, exc
            )
            return chunk, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=min(_workers(), len(chunks))) as pool:
        answers = list(pool.map(run, chunks))
    return assemble(text, answers)
