"""User-facing product naming.

The Python package keeps the historical ``quantagent`` import path for
compatibility. External surfaces should use the Mako brand.
"""

PRODUCT_NAME = "Mako"
PRODUCT_SIGIL = "MK"
PACKAGE_DISTRIBUTION = "open-mako"
PRIMARY_CLI = "mako"
ALT_CLI = "openmako"
LEGACY_CLI = "qagent"
LEGACY_PRODUCT_NAME = "QuantAgent"
TAGLINE = "local-first auditable agent runtime"


def cli_pair() -> str:
    return f"`{PRIMARY_CLI}` or `{ALT_CLI}` (`{LEGACY_CLI}` still works)"
