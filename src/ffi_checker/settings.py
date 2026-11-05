"""Shared settings helpers: `.env` loading and trusting the operating system's certificates."""

from __future__ import annotations

import os


def load_settings() -> None:
    """Read a `.env` file (searched from the current folder upwards) into environment variables.

    Values already set in the environment win over the file, so you can still
    override a single setting from the command line.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # python-dotenv not installed: rely on real env vars only
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)


def use_system_certificates() -> None:
    """Make Python trust the operating system's certificate store.

    Many company networks inspect HTTPS traffic and re-sign it with a company
    certificate. Windows already trusts that certificate, but Python ships its own
    list and does not, which gives "self-signed certificate in certificate chain".
    `truststore` makes Python use the OS list instead. Harmless on networks
    without inspection. Set FFI_SYSTEM_CERTS=0 to turn it off.
    """
    if os.environ.get("FFI_SYSTEM_CERTS", "1") == "0":
        return
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()
