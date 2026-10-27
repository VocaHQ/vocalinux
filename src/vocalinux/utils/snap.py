"""Facts about the Snap build that the rest of the app has to account for.

The snap runs under strict confinement and builds whisper.cpp from source for
the plain x86-64 baseline with no GPU backend (see ``snap/snapcraft.yaml``).
Host GPU tools such as ``nvidia-smi`` and ``vulkaninfo`` are not visible inside
it either, so probing for them only produces misleading "not found" errors.
"""

import os
from typing import Mapping, Optional

#: Shown wherever the snap would otherwise offer or probe for a GPU backend.
SNAP_GPU_NOTE = (
    "The Snap build runs whisper.cpp on the CPU. For GPU acceleration, "
    "install the AppImage or use install.sh."
)


def running_in_snap(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Whether this process runs inside the Vocalinux snap."""
    env = os.environ if environ is None else environ
    return bool(env.get("SNAP_NAME") or env.get("SNAP"))
