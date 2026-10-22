"""Page furniture: lines a PDF repeats at the top or bottom of its pages.

Running headers, running footers, copyright lines and page numbers sit inside criterion
lists wherever a list crosses a page. Left in, the segmentation model copies them into
`interruptions` -- the field behind every whitespace runaway measured on 2026-10-21 -- and
quotes a section's end at the last line before them (CAROLINA synopsis, exclusion 16 of 20).

A line is furniture when, with every run of digits read as one mark, it occurs within the
first or last :data:`EDGE_LINES` visible lines of at least half of the pages of one parity
(journals alternate their running heads between odd and even pages), and on at least
:data:`MIN_PAGES` pages. Position, repetition and digit runs only: what a line says is
never read. Measured on the nine corpus PDFs: no removed line lies inside a criterion of
the hand-made truth (tests/test_page_layout.py).
"""

from __future__ import annotations

from collections import defaultdict

from src.utils.span_match import fold

#: Visible lines at each end of a page searched for furniture.
EDGE_LINES = 8
#: Fewest pages a line must recur on.
MIN_PAGES = 3
#: Share of the pages of one parity a line must recur on.
MIN_SHARE = 0.5

_DIGITS = str.maketrans("0123456789", "##########")


def _shape(line: str) -> str:
    """The line in comparison form with each run of digits as one ``#``."""
    form = fold(line)[0].translate(_DIGITS)
    return "".join(c for i, c in enumerate(form) if c != "#" or i == 0 or form[i - 1] != "#")


def page_furniture(raw: str) -> list[tuple[int, int]]:
    """Offsets of the furniture lines of a ``pdftotext`` rendering.

    :param raw: the text with its form feeds (one per page break).
    :returns: ``(start, end)`` of each furniture line, its line break excluded, in order.
    """
    pages: list[list[tuple[int, int, str]]] = []
    offset = 0
    for page in raw.split("\f"):
        lines, at = [], offset
        for line in page.split("\n"):
            if fold(line)[0]:
                lines.append((at, at + len(line), _shape(line)))
            at += len(line) + 1
        pages.append(lines)
        offset += len(page) + 1
    if len(pages) < MIN_PAGES:
        return []
    seen: dict[tuple[str, str], set[int]] = defaultdict(set)
    for number, lines in enumerate(pages):
        for zone, edge in (("top", lines[:EDGE_LINES]), ("bottom", lines[-EDGE_LINES:])):
            for _lo, _hi, shape in edge:
                seen[(zone, shape)].add(number)
    per_parity = [len(range(parity, len(pages), 2)) for parity in (0, 1)]
    furniture = {
        key
        for key, numbers in seen.items()
        if len(numbers) >= MIN_PAGES
        and any(
            sum(1 for n in numbers if n % 2 == parity) >= MIN_SHARE * per_parity[parity]
            for parity in (0, 1)
        )
    }
    found = []
    for lines in pages:
        for position, (lo, hi, shape) in enumerate(lines):
            top = position < EDGE_LINES and ("top", shape) in furniture
            bottom = len(lines) - position <= EDGE_LINES and ("bottom", shape) in furniture
            if top or bottom:
                found.append((lo, hi))
    return found


def without_page_furniture(raw: str) -> str:
    """The text the segmentation step reads: furniture lines removed, page breaks as line breaks.

    :param raw: a ``pdftotext`` rendering, or any text (without form feeds it is unchanged).
    :returns: the text with each furniture line and its line break removed.
    """
    kept, cursor = [], 0
    for lo, hi in page_furniture(raw):
        kept.append(raw[cursor:lo])
        cursor = hi + 1
    kept.append(raw[cursor:])
    return "".join(kept).replace("\f", "\n")
