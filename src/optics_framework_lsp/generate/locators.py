# What kind of thing a locator is, by the rules the framework itself applies.
#
# `determine_element_type` in optics-framework sorts every locator into one of seven kinds
# before any strategy sees it, and a generated script that guesses differently looks for the
# wrong thing. It cannot import that function -- this package depends on no framework -- so
# the rules are restated here, and a test holds them to the same answers.
#
# One deliberate difference: `text_only:` is its own kind here where the framework calls it
# Text. The prefix is an instruction to skip the element source and use text detection, and
# that is the one thing a generated script cannot do, so it has to be told apart.

from __future__ import annotations

IMAGE = (".png", ".jpg", ".jpeg", ".bmp")

# A tag followed by `[`, `#` or `.` is a css selector, as the framework reads it.
_CSS_TAGS = (
    "input", "button", "div", "span", "a", "img", "select", "textarea",
    "form", "label", "p", "h1", "h2", "h3", "h4", "h5", "h6",
)


def kind(locator: str) -> str:
    """One of: text_only, image, css, xpath, id, klass, text."""
    text = locator.strip()
    lowered = text.lower()

    if lowered.startswith("text_only:"):
        return "text_only"
    if lowered.startswith("text="):
        return "text"
    if lowered.endswith(IMAGE):
        return "image"
    if lowered.startswith("css="):
        return "css"
    if lowered.startswith("xpath=") or text.startswith(("/", "//", "(")):
        return "xpath"
    if lowered.startswith("id:"):
        return "id"
    if lowered.startswith(("android.", "xcui")):
        return "klass"

    # A `#id` is only css when what follows starts a valid identifier; `#91` is text.
    css_id = len(text) > 1 and text[0] == "#" and (text[1].isalpha() or text[1] in "_-")
    css_tag = any(lowered.startswith(tag + c) for tag in _CSS_TAGS for c in ("[", "#", "."))
    if ("[" in text and "]" in text) or text.startswith(".") or css_id or css_tag:
        return "css"
    return "text"


def normalise(locator: str) -> str:
    """The locator as the generated script should carry it.

    Two kinds arrive wearing a prefix that is the framework's rather than the element's, and
    a third names a class where every target already reads a path: a class is the node test
    of the xpath that finds one, so writing it that way needs no second lookup.
    """
    text = locator.strip()
    found = kind(text)
    if found == "xpath" and text.lower().startswith("xpath="):
        return text[len("xpath=") :]
    if found == "text" and text.lower().startswith("text="):
        return text[len("text=") :]
    if found == "klass":
        return f"//{text}"
    return text


# Why a kind has no native form. A target adds its own reasons for the kinds it does carry.
REFUSED = {
    "text_only": "asks for text detection, and a generated script has no ocr to do it with",
    "image": "is an image template, and no native query matches one",
    "css": "is a css selector, which a native accessibility tree has no notion of",
    "id": "uses the `id:` prefix, which no locator strategy claims even in the framework",
}
