"""Guards for the YAML-owned installer package inventory."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    installer = (ROOT / "install.d" / "system_dependencies.sh").read_text(encoding="utf-8")
    assert '"$DEBIAN_MAJOR" -lt 12' in installer


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
