"""Guards for the YAML-owned installer package inventory."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "distro-package-map.yaml"
TARGET = ROOT / "install.d" / "package_map.sh"
GENERATOR = ROOT / "scripts" / "generate_distro_package_map.py"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("generate_distro_package_map", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generated_package_map_matches_yaml() -> None:
    """A YAML edit cannot leave the installer using yesterday's packages."""
    generator = _load_generator()
    assert TARGET.read_text(encoding="utf-8") == generator.render(generator.load_map())


def test_generated_package_map_is_valid_bash() -> None:
    """The committed artifact must remain safe for install.sh to source."""
    result = subprocess.run(["bash", "-n", str(TARGET)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_supported_debian_maps_start_at_debian_12() -> None:
    """Do not retain an EOL Debian 11 package branch in the source of truth."""
    distributions = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["distributions"]
    debian_maps = {name for name in distributions if name.startswith("debian_")}
    assert debian_maps == {"debian_12", "debian_13_plus"}


def _resolve_debian_map(
    distro_id: str, version: str, *, modern_gi: bool
) -> subprocess.CompletedProcess:
    script = f"""
source {TARGET!s}
source {ROOT / 'install.d' / 'system_dependencies.sh'!s}
print_error() {{ echo "$*"; }}
apt-cache() {{ [ "$HAS_MODERN_GI" = yes ]; }}
DISTRO_ID="$1"
DISTRO_VERSION="$2"
resolve_debian_package_map_key
"""
    return subprocess.run(
        ["bash", "-c", script, "bash", distro_id, version],
        capture_output=True,
        text=True,
        env={"HAS_MODERN_GI": "yes" if modern_gi else "no"},
    )


def test_native_debian_version_selects_supported_map() -> None:
    """Debian itself uses VERSION_ID and rejects its EOL releases."""
    assert _resolve_debian_map("debian", "11", modern_gi=False).returncode != 0
    assert _resolve_debian_map("debian", "12", modern_gi=True).stdout.strip() == "debian_12"
    assert _resolve_debian_map("debian", "13", modern_gi=False).stdout.strip() == "debian_13_plus"


def test_debian_derivative_ignores_unrelated_product_version() -> None:
    """A derivative's VERSION_ID must not be interpreted as a Debian release."""
    legacy = _resolve_debian_map("mx", "11", modern_gi=False)
    modern = _resolve_debian_map("kali", "2026.3", modern_gi=True)
    assert legacy.returncode == 0
    assert legacy.stdout.strip() == "debian_12"
    assert modern.stdout.strip() == "debian_13_plus"


def test_suse_appindicator_alternatives_are_required(tmp_path: Path) -> None:
    """Generation fails before an empty openSUSE fallback loop reaches users."""
    generator = _load_generator()
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document["distributions"]["suse"]["appindicator"] = []
    invalid_source = tmp_path / "invalid.yaml"
    invalid_source.write_text(yaml.safe_dump(document), encoding="utf-8")
    generator.SOURCE = invalid_source
    with pytest.raises(ValueError, match="suse.appindicator"):
        generator.load_map()


def test_installer_uses_generated_inventory_instead_of_package_lists() -> None:
    """Package data belongs in YAML; handwritten shell owns only selection policy."""
    installer = (ROOT / "install.d" / "system_dependencies.sh").read_text(encoding="utf-8")
    assert 'load_distro_package_map "$PACKAGE_MAP_KEY"' in installer
    for old_variable in (
        "APT_PACKAGES_UBUNTU",
        "APT_PACKAGES_DEBIAN_BASE",
        "DNF_PACKAGES",
        "PACMAN_PACKAGES",
        "ZYPPER_PACKAGES",
        "EMERGE_PACKAGES",
        "APK_PACKAGES",
        "XBPS_PACKAGES",
        "EOPKG_PACKAGES",
    ):
        assert f"local {old_variable}=" not in installer


def test_unsupported_distros_do_not_read_uninitialized_package_arrays() -> None:
    """The existing non-interactive unsupported-distro path may continue safely."""
    installer = (ROOT / "install.d" / "system_dependencies.sh").read_text(encoding="utf-8")
    guard = installer.index('[[ -z "${XDOTOOL_PACKAGES+x}" ]]')
    first_read = installer.index("${XDOTOOL_PACKAGES[0]}")
    assert guard < first_read
