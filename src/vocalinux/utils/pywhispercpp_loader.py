"""Locate and preload pywhispercpp's bundled shared libraries.

Some source builds place libwhisper/libggml next to the Python extension
without an RPATH. Preloading by absolute path lets the dynamic loader satisfy
the extension's libwhisper.so.1 dependency before importing pywhispercpp, and
keeps non-dictation entry points (e.g. ``--transcribe-file``) working on such
installs.
"""

import ctypes
import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_PRELOADED_LIBS: list[ctypes.CDLL] = []


def find_shared_library_dirs() -> list[str]:
    """Find bundled pywhispercpp native library directories without importing it."""
    candidate_dirs: list[Path] = []

    for module_name in ("_pywhispercpp", "pywhispercpp"):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is None:
            continue

        if spec.origin:
            module_dir = Path(spec.origin).resolve().parent
            candidate_dirs.extend(
                [
                    module_dir,
                    module_dir / ".libs",
                    module_dir / "lib",
                    module_dir / "pywhispercpp.libs",
                    module_dir.parent / "pywhispercpp.libs",
                ]
            )

        if spec.submodule_search_locations:
            for location in spec.submodule_search_locations:
                package_dir = Path(location).resolve()
                candidate_dirs.extend(
                    [
                        package_dir,
                        package_dir / ".libs",
                        package_dir / "lib",
                        package_dir.parent / "pywhispercpp.libs",
                    ]
                )

    for path_entry in sys.path:
        if not path_entry:
            continue
        path_root = Path(path_entry).resolve()
        candidate_dirs.append(path_root / "pywhispercpp.libs")

    library_dirs: list[str] = []
    seen: set[str] = set()
    for candidate_dir in candidate_dirs:
        try:
            resolved_dir = str(candidate_dir.resolve())
            if resolved_dir in seen or not candidate_dir.is_dir():
                continue

            has_native_lib = any(candidate_dir.glob("libwhisper*.so*")) or any(
                candidate_dir.glob("libggml*.so*")
            )
        except (OSError, TypeError, ValueError):
            # TypeError/ValueError can surface when tests monkey-patch os.stat or
            # when pathlib internals receive unexpected types from mocks.
            continue

        if has_native_lib:
            seen.add(resolved_dir)
            library_dirs.append(resolved_dir)

    return library_dirs


def preload_shared_libraries() -> None:
    """Preload bundled pywhispercpp shared libraries for source-built installs."""
    if _PRELOADED_LIBS:
        return

    libraries: list[Path] = []
    for library_dir in find_shared_library_dirs():
        root = Path(library_dir)
        libraries.extend(sorted(root.glob("libggml*.so*")))
        libraries.extend(sorted(root.glob("libwhisper*.so*")))

    if not libraries:
        return

    pending = list(dict.fromkeys(libraries))
    loaded: list[ctypes.CDLL] = []
    last_errors: dict[str, OSError] = {}
    mode = getattr(ctypes, "RTLD_GLOBAL", 0)

    # Native libs can depend on each other. Retry while progress is made so a
    # dependency loaded earlier in the same directory can unlock later libraries.
    while pending:
        loaded_this_pass = False
        for library_path in pending[:]:
            try:
                loaded.append(ctypes.CDLL(str(library_path), mode=mode))
                pending.remove(library_path)
                loaded_this_pass = True
            except OSError as e:
                last_errors[str(library_path)] = e

        if not loaded_this_pass:
            break

    _PRELOADED_LIBS.extend(loaded)

    if pending:
        logger.debug(
            "Could not preload all pywhispercpp native libraries: %s",
            {str(path): str(last_errors.get(str(path))) for path in pending},
        )
