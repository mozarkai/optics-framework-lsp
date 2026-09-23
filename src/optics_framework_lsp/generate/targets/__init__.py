# The script kinds `generate` can write.
#
# A target owns everything that differs between them: how a name becomes an identifier, how
# a locator becomes a query, which keywords it can express, and how the whole file is laid
# out. The driver in the package above owns only what does not differ — walking the suite,
# resolving params, and collecting what did not translate.

from __future__ import annotations

from types import ModuleType

from . import uiautomator2

TARGETS: dict[str, ModuleType] = {
    uiautomator2.NAME: uiautomator2,
}
