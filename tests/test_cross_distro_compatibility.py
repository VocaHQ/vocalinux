"""
Test cross-distro compatibility features.

This module tests the cross-distribution compatibility features including:
- Dynamic GI_TYPELIB_PATH detection
- Wrapper script generation with correct paths
- Desktop entry configuration
"""

import os
from pathlib import Path

import pytest


def get_repo_root() -> Path:
    """Get the repository root directory."""
    # Start from current file and traverse up to find repo root
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        # Check for common repo indicators
        if (parent / ".git").exists() or (parent / "install.sh").exists():
            return parent
        # Also check if we're in a 'vocalinux' subdirectory (CI structure)
        if parent.name == "vocalinux" and (parent.parent / "vocalinux" / "install.sh").exists():
            return parent.parent / "vocalinux"
    # Fallback: use parent of tests directory
    return current.parent.parent.parent


REPO_ROOT = get_repo_root()


class TestCrossDistroCompatibility:
    """Test cross-distro compatibility features."""

    @pytest.fixture
    def install_sh_content(self):
        """Fixture to load install.sh content."""
        install_sh_path = REPO_ROOT / "install.sh"
        if not install_sh_path.exists():
            pytest.skip(f"install.sh not found at {install_sh_path}")
        return install_sh_path.read_text()

    @pytest.fixture
    def workflow_content(self):
        """Fixture to load workflow content."""
        workflow_path = REPO_ROOT / ".github" / "workflows" / "unified-pipeline.yml"
        if not workflow_path.exists():
            pytest.skip(f"Workflow file not found at {workflow_path}")
        return workflow_path.read_text()

    def test_detect_typelib_path_function_exists(self, install_sh_content):
        """Test that detect_typelib_path function exists in install.sh."""
        assert (
            "detect_typelib_path()" in install_sh_content
        ), "detect_typelib_path function should exist"
        assert (
            "pkg-config --variable=typelibdir" in install_sh_content
        ), "Should use pkg-config for detection"

    def test_no_hardcoded_gi_typelib_path_in_verification(self, install_sh_content):
        """Test that package verification uses dynamic GI_TYPELIB_PATH."""
        # The verification function should use the detected path, not hardcoded
        assert (
            "verify_package_installed()" in install_sh_content
        ), "verify_package_installed function should exist"

        # Check that it uses GI_TYPELIB_DETECTED variable
        verify_section = install_sh_content[
            install_sh_content.find("verify_package_installed()") : install_sh_content.find(
                "verify_package_installed()"
            )
            + 500
        ]
        assert (
            "GI_TYPELIB_DETECTED" in verify_section or '"$GI_TYPELIB_DETECTED"' in verify_section
        ), "verify_package_installed should use GI_TYPELIB_DETECTED variable"

    def test_wrapper_script_uses_detected_path(self, install_sh_content):
        """Test that wrapper scripts use the detected GI_TYPELIB_PATH."""
        # Check that wrapper script creation uses GI_TYPELIB_DETECTED
        assert (
            "export GI_TYPELIB_PATH=$GI_TYPELIB_DETECTED" in install_sh_content
        ), "Wrapper script should export GI_TYPELIB_PATH with detected value"

    def test_desktop_entry_uses_detected_path(self, install_sh_content):
        """Test that desktop entry uses detected GI_TYPELIB_PATH."""
        # The sed command for desktop entry should use the detected path
        assert (
            "GI_TYPELIB_PATH=$GI_TYPELIB_DETECTED" in install_sh_content
            or r"GI_TYPELIB_PATH=${GI_TYPELIB_DETECTED}" in install_sh_content
        ), "Desktop entry sed command should use GI_TYPELIB_DETECTED"

        # Should NOT have hardcoded /usr/lib/girepository-1.0 in desktop entry section
        desktop_start = install_sh_content.find("install_desktop_entry()")
        if desktop_start == -1:
            pytest.skip("install_desktop_entry function not found")
        desktop_section = install_sh_content[desktop_start : desktop_start + 1000]
        if "sed -i" in desktop_section and "vocalinux.desktop" in desktop_section:
            assert (
                "/usr/lib/girepository-1.0"
                not in desktop_section.split("sed -i")[1].split("vocalinux.desktop")[0]
            ), "Desktop entry should not hardcode /usr/lib/girepository-1.0 path"

    def test_detect_typelib_path_with_pkgconfig(self, install_sh_content):
        """Test that detect_typelib_path uses pkg-config when available."""
        # Extract the detect_typelib_path function
        func_start = install_sh_content.find("detect_typelib_path() {")
        if func_start == -1:
            pytest.skip("detect_typelib_path function not found")
        func_end = install_sh_content.find("}", func_start)
        func_content = install_sh_content[func_start:func_end]

        # Should check for pkg-config first
        assert "pkg-config" in func_content, "Should check for pkg-config"
        assert "gobject-introspection-1.0" in func_content, "Should query gobject-introspection-1.0"

    def test_detect_typelib_path_fallback_paths(self, install_sh_content):
        """Test that detect_typelib_path has fallback paths for various distros."""
        # Should have fallback paths for different distros
        expected_paths = [
            "/usr/lib/x86_64-linux-gnu/girepository-1.0",  # Ubuntu/Debian x86_64
            "/usr/lib/aarch64-linux-gnu/girepository-1.0",  # ARM64
            "/usr/lib64/girepository-1.0",  # Fedora/RHEL
            "/usr/lib/girepository-1.0",  # Arch and fallback
        ]

        for path in expected_paths:
            assert path in install_sh_content, f"Should have fallback path: {path}"

    def test_opensuse_dependency_mapping_uses_tumbleweed_package_names(self, install_sh_content):
        """Test that openSUSE uses Tumbleweed-compatible dependency resolution."""
        assert "suse_python_package_prefix()" in install_sh_content
        assert "suse_python_package_candidates()" in install_sh_content
        assert "typelib-1_0-AyatanaAppIndicator3-0_1" in install_sh_content
        assert "typelib-1_0-Notify-0_7" in install_sh_content
        assert "libnotify4" in install_sh_content
        assert "suse_install_appindicator_runtime" in install_sh_content
        assert "shaderc glslang-devel glslang" in install_sh_content

        zypper_line = next(
            line for line in install_sh_content.splitlines() if "local ZYPPER_PACKAGES=" in line
        )
        assert "python3-devel" not in zypper_line
        assert "python3-virtualenv" not in zypper_line
        assert "libappindicator-gtk3" not in zypper_line
        assert "glslang" not in zypper_line

    def test_rpm_arch_install_glslc_not_glslang(self, install_sh_content):
        """ggml Vulkan needs glslc (shaderc). glslangValidator is not a substitute (#604)."""
        dnf_line = next(
            line for line in install_sh_content.splitlines() if "local DNF_PACKAGES=" in line
        )
        pacman_line = next(
            line for line in install_sh_content.splitlines() if "local PACMAN_PACKAGES=" in line
        )
        assert "glslc" in dnf_line
        assert "patchelf" in dnf_line
        assert "glslang" not in dnf_line
        assert "shaderc" in pacman_line
        assert "patchelf" in pacman_line
        assert "glslang" not in pacman_line
        assert (
            "Fedora: sudo dnf install vulkan-loader-devel vulkan-tools glslc patchelf"
            in install_sh_content
        )
        assert (
            "Arch: sudo pacman -S vulkan-headers vulkan-tools shaderc patchelf"
            in install_sh_content
        )
        emerge_line = next(
            line for line in install_sh_content.splitlines() if "local EMERGE_PACKAGES=" in line
        )
        assert "media-libs/shaderc" in emerge_line
        assert "dev-util/patchelf" in emerge_line
        assert "sys-devel/patchelf" not in emerge_line

    def test_skip_system_deps_option_is_implemented(self, install_sh_content):
        """Test that the documented --skip-system-deps option is parsed and honored."""
        assert "SKIP_SYSTEM_DEPS" in install_sh_content
        assert "--skip-system-deps" in install_sh_content
        assert "Skipping system dependency installation" in install_sh_content

    def test_noninteractive_tty_fallback_does_not_abort(self, install_sh_content):
        """Test that missing controlling TTY falls back to non-interactive mode."""
        assert "{ true < /dev/tty; } 2>/dev/null" in install_sh_content
        assert "exec < /dev/tty" in install_sh_content
        assert 'NON_INTERACTIVE="yes"' in install_sh_content

    def test_ci_workflow_uses_dynamic_detection(self, workflow_content):
        """Test that CI workflow uses dynamic GI_TYPELIB_PATH detection."""
        # Should use pkg-config or dynamic detection
        assert (
            "pkg-config --variable=typelibdir" in workflow_content
        ), "CI workflow should use pkg-config for GI_TYPELIB_PATH"


class TestResourceManagerCrossDistro:
    """Test ResourceManager cross-distro path handling."""

    def test_resource_manager_has_xdg_support(self):
        """Test that ResourceManager supports XDG directories."""
        from vocalinux.utils.resource_manager import ResourceManager

        rm = ResourceManager()
        resources_dir = rm.resources_dir

        # Should be a valid path string
        assert isinstance(resources_dir, str), "resources_dir should be a string"
        assert len(resources_dir) > 0, "resources_dir should not be empty"


class TestRecognitionManagerCrossDistro:
    """Test RecognitionManager cross-distro model path handling."""

    def test_system_model_paths_exists(self):
        """Test that system model paths configuration exists."""
        from vocalinux.speech_recognition.recognition_manager import SYSTEM_MODELS_DIRS

        # Should be a list of paths
        assert isinstance(SYSTEM_MODELS_DIRS, list), "SYSTEM_MODELS_DIRS should be a list"
        assert len(SYSTEM_MODELS_DIRS) > 0, "SYSTEM_MODELS_DIRS should not be empty"

        # Should include XDG paths
        has_xdg = any("/share/" in path for path in SYSTEM_MODELS_DIRS)
        assert has_xdg, "SYSTEM_MODELS_DIRS should include XDG paths"


class TestDocumentation:
    """Test that documentation is accurate."""

    def test_distro_compatibility_documentation_exists(self):
        """Test that DISTRO_COMPATIBILITY.md exists and is accurate."""
        docs_path = REPO_ROOT / "docs" / "DISTRO_COMPATIBILITY.md"

        if not docs_path.exists():
            pytest.skip(f"DISTRO_COMPATIBILITY.md not found at {docs_path}")

        content = docs_path.read_text()

        # Should mention the dynamic path detection
        assert (
            "pkg-config" in content or "detect_typelib_path" in content
        ), "Should document dynamic path detection"

        # Should mention supported distros
        expected_distros = ["Ubuntu", "Debian", "Fedora", "Arch", "openSUSE"]
        for distro in expected_distros:
            assert distro in content, f"Should mention {distro} support"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
