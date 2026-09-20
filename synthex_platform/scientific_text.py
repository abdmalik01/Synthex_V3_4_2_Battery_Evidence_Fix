"""Conservative scientific-text normalization for comparison only.

The helpers in this module never mutate archived raw values or evidence.  They
only make typography-safe comparison keys for source verification, benchmark
association, and canonical condition identity.
"""

from __future__ import annotations

import re
import unicodedata


_TYPOGRAPHY_TRANSLATION = str.maketrans({
    "\u00a0": " ",  # no-break space
    "\u2007": " ",  # figure space
    "\u202f": " ",  # narrow no-break space
    "\u2212": "-",  # minus sign
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00ad": "",  # soft hyphen
    "\u2219": "\u00b7",  # bullet operator -> middle dot
    "\u22c5": "\u00b7",  # dot operator -> middle dot
})


def normalize_scientific_text(value: object | None, *, casefold: bool = True) -> str:
    """Return a narrow typography-normalized comparison key.

    NFKC safely unifies compatibility forms such as micro signs, Ohm glyphs,
    and superscript digits.  The small-circle temperature glyph is normalized
    only when it is used directly before C or F, so unrelated bullets are not
    rewritten.  Scientific names and concepts are never aliased here.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).translate(_TYPOGRAPHY_TRANSLATION)
    text = re.sub(r"(?<=\d)\s*\u25e6\s*(?=[CFcf]\b)", " \u00b0", text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold() if casefold else text
