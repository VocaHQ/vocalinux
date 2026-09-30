"""Guards for the YAML-owned installer package inventory."""

import importlib.util
import os
import shlex
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
    distro_id: str, version: str, *, modern_gi: bool, refresh_fails: bool = False
) -> subprocess.CompletedProcess:
    script = f"""
set -eu
source {shlex.quote(str(TARGET))}
source {shlex.quote(str(ROOT / 'install.d' / 'system_dependencies.sh'))}
print_error() {{ echo "$*"; }}
EXIT_NETWORK=3
EXIT_MISSING_DEPS=2
CACHE_READY=no
sudo() {{
    [ "$*" = "apt update" ] || exit 99
    echo "refreshing indexes"
    [ "$REFRESH_FAILS" = no ] || return 1
    CACHE_READY=yes
}}
apt-cache() {{
    [ "$*" = "show $DEBIAN_13_PLUS_PROBE_PACKAGE" ] || exit 99
    [ "$CACHE_READY" = yes ] && [ "$HAS_MODERN_GI" = yes ]
}}
DISTRO_ID="$1"
DISTRO_VERSION="$2"
resolve_debian_package_map_key
"""
    return subprocess.run(
        ["bash", "-c", script, "bash", distro_id, version],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HAS_MODERN_GI": "yes" if modern_gi else "no",
            "REFRESH_FAILS": "yes" if refresh_fails else "no",
        },
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
    assert "refreshing indexes" in modern.stderr


def test_debian_probe_does_not_fall_back_on_network_failure() -> None:
    result = _resolve_debian_map("derivative", "7", modern_gi=True, refresh_fails=True)
    assert result.returncode == 3
    assert "debian_12" not in result.stdout


@pytest.mark.parametrize("field", ["vulkan", "shader_compiler"])
@pytest.mark.parametrize("value", [None, []])
def test_required_suse_build_inventory(tmp_path: Path, field: str, value: Any) -> None:
    generator = _load_generator()
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if value is None:
        del document["distributions"]["suse"][field]
    else:
        document["distributions"]["suse"][field] = value
    generator.SOURCE = tmp_path / "invalid.yaml"
    generator.SOURCE.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match=f"suse.{field}"):
        generator.load_map()


def test_text_tool_cannot_silently_drop_second_package(tmp_path: Path) -> None:
    generator = _load_generator()
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document["distributions"]["ubuntu"]["text_input"]["wtype"].append("extra-package")
    generator.SOURCE = tmp_path / "invalid.yaml"
    generator.SOURCE.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one package"):
        generator.load_map()


def test_suse_suffix_spelling_is_owned_by_yaml(tmp_path: Path) -> None:
    generator = _load_generator()
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document["distributions"]["suse"]["python_packages"]["pip"] = "renamed-pip"
    generator.SOURCE = tmp_path / "map.yaml"
    generator.SOURCE.write_text(yaml.safe_dump(document), encoding="utf-8")
    rendered = generator.render(generator.load_map())
    assert "PYTHON_PIP_SUFFIX=renamed-pip" in rendered


def test_suse_python_roles_are_named_not_positional(tmp_path: Path) -> None:
    generator = _load_generator()
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    del document["distributions"]["suse"]["python_packages"]["pip"]
    document["distributions"]["suse"]["python_packages"]["unexpected"] = "pip"
    generator.SOURCE = tmp_path / "invalid.yaml"
    generator.SOURCE.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="python_packages must define"):
        generator.load_map()


@pytest.mark.parametrize(
    "old,new",
    [
        ("schema_version: 1", "schema_version: 99\nschema_version: 1"),
        ("wtype: [wtype]", "wtype: [discarded]\n      wtype: [wtype]"),
    ],
)
def test_duplicate_keys_are_rejected(tmp_path: Path, old: str, new: str) -> None:
    generator = _load_generator()
    generator.SOURCE = tmp_path / "invalid.yaml"
    generator.SOURCE.write_text(SOURCE.read_text().replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        generator.load_map()


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
