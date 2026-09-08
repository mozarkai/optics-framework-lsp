# Columns on the wire are not columns in Python.
#
# LSP counts a line in utf-16 code units unless the client and server agree otherwise,
# and clients that offer a choice all offer utf-16. Python counts code points. The two
# agree for every character in the basic plane and disagree for the rest — an emoji, a
# rarer CJK ideograph — which is one code point and two units.
#
# Everything inside this package counts code points, because that is what slicing a
# `str` does. These convert at the edge, and nowhere else, so the two never mix.

from __future__ import annotations


def to_utf16(line: str, index: int) -> int:
    """A code-point index into `line`, as the column a client expects."""
    if line.isascii():
        return index
    return index + sum(1 for char in line[:index] if char > "￿")


def from_utf16(line: str, unit: int) -> int:
    """A client's column, as a code-point index into `line`."""
    if line.isascii():
        return unit

    units = 0
    for index, char in enumerate(line):
        if units >= unit:
            return index
        units += 2 if char > "￿" else 1
    return len(line)
