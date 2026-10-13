# Locators

optics sorts every locator into a kind before it looks for anything. Sort it the same way,
in this order - the first rule that fits wins:

| Locator | Kind |
| --- | --- |
| starts with `text_only:` | text_only |
| starts with `text=` | text (prefix removed) |
| ends with `.png` `.jpg` `.jpeg` `.bmp` | image |
| starts with `css=` | css |
| starts with `xpath=`, `/`, `//` or `(` | xpath (`xpath=` removed) |
| starts with `id:` | id |
| starts with `android.` or `xcui` | class - written as `//<class>` |
| has `[` and `]`, starts with `.`, is `#name`, or is `tag[`/`tag#`/`tag.` for an HTML tag | css |
| anything else | text (an accessibility id) |

## Refused on both targets

| Kind | Why |
| --- | --- |
| text_only | asks for text detection, and a script has no OCR |
| image | an image template - no native query matches one |
| css | a native accessibility tree has no CSS |
| id | the `id:` prefix is claimed by no strategy, even in optics |

## Per target

- **Android:** an xpath naming `XCUIElementType` is refused - it is an iOS class.
- **iOS:** an xpath is carried into the script as written and evaluated on the device - see
  "How an xpath runs" in `references/ios.md` for what it reads. An xpath outside that is
  refused; so is one naming an Android class.

A dropped locator is reported with its reason. The element keeps its other locators. An
element left with none is only unusable *as a locator*: when a step reads it as a value (a
`Run Loop` list, a typed text), its value is still there to inline.
