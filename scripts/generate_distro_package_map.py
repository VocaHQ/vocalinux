#!/usr/bin/env python3
"""Generate the installer's shell package map from its YAML source."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "distro-package-map.yaml"
TARGET = ROOT / "install.d" / "package_map.sh"
REQUIRED_DISTRIBUTIONS = {
    "alpine",
    "arch",
    "debian_12",
    "debian_13_plus",
    "fedora",
    "gentoo",
    "mageia",
    "solus",
    "suse",
    "ubuntu",
    "void",
}
LIST_FIELDS = {
    "appindicator",
    "gi_development",
    "optional_system",
    "shader_compiler",
    "system",
    "vulkan",
}
SCALAR_FIELDS = {"selection_probe"}
TEXT_TOOLS = {"wtype", "xdotool", "ydotool"}
SUSE_PYTHON_ROLES = {"pip", "gobject", "gobject_cairo", "devel", "virtualenv", "venv"}


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently dropping inventory."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("package map keys must be strings")
            if key in result:
                raise ValueError(f"duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _package_list(value: Any, location: str, *, required: bool = False) -> list[str]:
    """Validate and return one package list."""
    if value is None and not required:
        return []
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{location} must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{location} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{location} contains duplicate packages")
    return value


def load_map() -> dict[str, dict[str, Any]]:
    """Load and validate the authoritative YAML package map."""
    document = yaml.load(SOURCE.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("distro package map must use schema_version: 1")
    distributions = document.get("distributions")
    if not isinstance(distributions, dict):
        raise ValueError("distro package map must define a distributions mapping")
    names = set(distributions)
    if names != REQUIRED_DISTRIBUTIONS:
        missing = ", ".join(sorted(REQUIRED_DISTRIBUTIONS - names)) or "none"
        extra = ", ".join(sorted(names - REQUIRED_DISTRIBUTIONS)) or "none"
        raise ValueError(f"distribution keys differ (missing: {missing}; extra: {extra})")

    for distro, config in distributions.items():
        if not isinstance(config, dict):
            raise ValueError(f"distributions.{distro} must be a mapping")
        unknown = set(config) - LIST_FIELDS - SCALAR_FIELDS - {"python_packages", "text_input"}
        if unknown:
            raise ValueError(f"distributions.{distro} has unknown fields: {sorted(unknown)}")
        _package_list(config.get("system"), f"distributions.{distro}.system", required=True)
        for field in LIST_FIELDS - {"system"}:
            _package_list(config.get(field), f"distributions.{distro}.{field}")
        selection_probe = config.get("selection_probe")
        if selection_probe is not None and (
            distro != "debian_13_plus"
            or not isinstance(selection_probe, str)
            or not selection_probe
        ):
            raise ValueError("selection_probe must be a non-empty string on debian_13_plus only")
        python_packages = config.get("python_packages")
        if python_packages is not None:
            if distro != "suse" or not isinstance(python_packages, dict):
                raise ValueError("python_packages must be a mapping on suse only")
            if set(python_packages) != SUSE_PYTHON_ROLES:
                raise ValueError(
                    f"distributions.suse.python_packages must define {sorted(SUSE_PYTHON_ROLES)}"
                )
            if any(not isinstance(value, str) or not value for value in python_packages.values()):
                raise ValueError("distributions.suse.python_packages values must be strings")
        text_input = config.get("text_input")
        if not isinstance(text_input, dict) or set(text_input) != TEXT_TOOLS:
            raise ValueError(f"distributions.{distro}.text_input must define {sorted(TEXT_TOOLS)}")
        for tool in TEXT_TOOLS:
            _package_list(
                text_input.get(tool),
                f"distributions.{distro}.text_input.{tool}",
                required=True,
            )
            if len(text_input[tool]) != 1:
                raise ValueError(
                    f"distributions.{distro}.text_input.{tool} needs exactly one package"
                )

    for distro in ("ubuntu", "fedora", "arch"):
        if len(distributions[distro].get("appindicator") or []) != 2:
            raise ValueError(f"distributions.{distro}.appindicator must define two fallbacks")
    if len(distributions["suse"].get("appindicator") or []) < 4:
        raise ValueError("distributions.suse.appindicator must define at least four alternatives")
    if not distributions["debian_13_plus"].get("selection_probe"):
        raise ValueError("distributions.debian_13_plus.selection_probe is required")
    if len(distributions["ubuntu"].get("gi_development") or []) != 2:
        raise ValueError("distributions.ubuntu.gi_development must define modern and legacy")
    for distro in ("ubuntu", "debian_12", "debian_13_plus"):
        if len(distributions[distro].get("shader_compiler") or []) < 2:
            raise ValueError(f"distributions.{distro}.shader_compiler needs a fallback")
    if "python_packages" not in distributions["suse"]:
        raise ValueError("distributions.suse.python_packages is required")
    for field in ("vulkan", "shader_compiler"):
        _package_list(distributions["suse"].get(field), f"suse.{field}", required=True)
    return distributions


def _array_assignment(name: str, values: list[str], indent: str = "            ") -> str:
    quoted = " ".join(shlex.quote(value) for value in values)
    return f"{indent}{name}=({quoted})"


def render(distributions: dict[str, dict[str, Any]]) -> str:
    """Render a deterministic Bash module from the validated map."""
    debian_13_probe = distributions["debian_13_plus"]["selection_probe"]
    lines = [
        "#!/bin/bash",
        "# Generated by scripts/generate_distro_package_map.py -- do not edit.",
        "# Regenerate with `just distro-packages` after editing",
        "# scripts/distro-package-map.yaml.",
        "",
        f"DEBIAN_13_PLUS_PROBE_PACKAGE={shlex.quote(debian_13_probe)}",
        "",
        "load_distro_package_map() {",
        '    local package_map_key="$1"',
        "",
        "    SYSTEM_PACKAGES=()",
        "    APPINDICATOR_PACKAGES=()",
        "    GI_DEVELOPMENT_PACKAGES=()",
        "    OPTIONAL_SYSTEM_PACKAGES=()",
        '    PYTHON_PIP_SUFFIX=""',
        '    PYTHON_GOBJECT_SUFFIX=""',
        '    PYTHON_GOBJECT_CAIRO_SUFFIX=""',
        '    PYTHON_DEVEL_SUFFIX=""',
        '    PYTHON_VIRTUALENV_SUFFIX=""',
        '    PYTHON_VENV_SUFFIX=""',
        "    SHADER_COMPILER_PACKAGES=()",
        "    VULKAN_PACKAGES=()",
        "    XDOTOOL_PACKAGES=()",
        "    WTYPE_PACKAGES=()",
        "    YDOTOOL_PACKAGES=()",
        "",
        '    case "$package_map_key" in',
    ]
    names = {
        "system": "SYSTEM_PACKAGES",
        "appindicator": "APPINDICATOR_PACKAGES",
        "gi_development": "GI_DEVELOPMENT_PACKAGES",
        "optional_system": "OPTIONAL_SYSTEM_PACKAGES",
        "shader_compiler": "SHADER_COMPILER_PACKAGES",
        "vulkan": "VULKAN_PACKAGES",
    }
    for distro, config in distributions.items():
        lines.append(f"        {distro})")
        for field, variable in names.items():
            values = _package_list(config.get(field), f"{distro}.{field}")
            if values:
                lines.append(_array_assignment(variable, values))
        python_packages = config.get("python_packages")
        if python_packages:
            for role in sorted(SUSE_PYTHON_ROLES):
                variable = f"PYTHON_{role.upper()}_SUFFIX"
                lines.append(f"            {variable}={shlex.quote(python_packages[role])}")
        text_input = config["text_input"]
        lines.append(_array_assignment("XDOTOOL_PACKAGES", text_input["xdotool"]))
        lines.append(_array_assignment("WTYPE_PACKAGES", text_input["wtype"]))
        lines.append(_array_assignment("YDOTOOL_PACKAGES", text_input["ydotool"]))
        lines.extend(["            ;;", ""])
    lines.extend(
        [
            "        *)",
            '            echo "Unknown distro package map key: $package_map_key" >&2',
            "            return 1",
            "            ;;",
            "    esac",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Generate the map, or check that the committed output is current."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the output is stale")
    args = parser.parse_args()
    try:
        generated = render(load_map())
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != generated:
            print(
                f"{TARGET.relative_to(ROOT)} is stale; run `just distro-packages`",
                file=sys.stderr,
            )
            return 1
        return 0

    TARGET.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
