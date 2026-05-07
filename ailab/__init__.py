"""ailab: LXD-based sandboxes for running AI tools safely on Ubuntu."""

import sys
from pathlib import Path

# When installed as a Debian package, pylxd is vendored here because it is
# not (yet) packaged for Debian. Its own dependencies are satisfied by the
# Debian packages listed in the ailab package Depends.
_vendor = Path(__file__).parent / "_vendor"
if _vendor.exists() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))

try:
    from importlib.metadata import version
    __version__ = version("ailab")
except Exception:
    __version__ = "0.0.0"
