# The framework's keyword signatures, from the generated table in `keywords.py`.
#
# Hardcoded rather than read from the user's install: importing `optics_framework.api.*`
# pulls numpy, cv2, pandas and skimage, so probing needs a ~342 MB install and fails outright
# when one of those is broken — leaving a project with no keyword diagnostics at all. Run
# `scripts/update_catalog.py` to refresh the table against a new optics release.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .keywords import KEYWORDS, OPTICS_VERSION


@dataclass(slots=True)
class Keyword:
    required: int
    variadic: bool
    # Positional names in order. Python forbids a defaulted param before a plain one, so
    # the first `required` of these are the mandatory ones.
    params: list[str]
    # The framework's own docstring, which is where the accepted values are written.
    doc: str = ""
    # What an omitted param falls back to, already repr'd, by param name.
    defaults: dict[str, str] = field(default_factory=dict)


Catalog = dict[str, Keyword]


def slug(name: str | None) -> str:
    """A step name as `_execute_single_keyword` resolves it. Whitespace and underscores
    both collapse: `keyword_map` is keyed by the Python method names, so `press_element`
    and `Press Element` are one keyword. Module names it looks up raw."""
    return " ".join((name or "").replace("_", " ").split()).lower()


# Copied out of the table so a caller mutating a Keyword cannot corrupt it.
CATALOG: Catalog = {
    name: Keyword(
        required=signature["required"],
        variadic=signature["variadic"],
        params=list(signature["params"]),
        doc=signature["doc"],
        defaults=dict(signature["defaults"]),
    )
    for name, signature in KEYWORDS.items()
}


def slots(
    step_name: str | None, params: Sequence[str], catalog: Catalog | None = None
) -> list[tuple[int, str]]:
    """Each param as the slot it binds and the value alone.

    `split_params_by_signature`'s rule: a `name=` binds that slot wherever it is written,
    the rest bind by position. A key naming no param stays part of the value, which keeps
    a locator like `text=Login` the element. Against the shipped signature by default.
    """
    found = (catalog if catalog is not None else CATALOG).get(slug(step_name))
    names = found.params if found else []

    bound: list[tuple[int, str]] = []
    free = 0
    for param in params:
        key, sep, value = param.partition("=")
        if sep and (key := key.strip()) in names:
            bound.append((names.index(key), value.strip()))
        else:
            bound.append((free, param))
            free += 1
    return bound
