"""Regression checks for installer CUDA diagnostics."""

import unittest
from pathlib import Path

import yaml

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
INSTALLER_MODULES = Path(__file__).resolve().parents[1] / "install.d"
PACKAGE_MAP = yaml.safe_load(
    (INSTALLER.parent / "scripts" / "distro-package-map.yaml").read_text(encoding="utf-8")
)["distributions"]


def _installer_source() -> str:
    parts = [INSTALLER, *sorted(INSTALLER_MODULES.glob("*.sh"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in parts)


class InstallerCudaDiagnosticsTests(unittest.TestCase):
    def test_installer_disables_user_site_packages(self) -> None:
        """Keep user-site packages out of the venv, activation script, and wrappers."""
        source = _installer_source()

        self.assertGreaterEqual(source.count("export PYTHONNOUSERSITE=1"), 4)
        self.assertIn('getattr(site, "ENABLE_USER_SITE", False)', source)

    def test_cuda_toolkit_validation_requires_complete_root(self) -> None:
        """CUDA roots must not be accepted when only a stale /usr/local/cuda exists."""
        source = _installer_source()

        self.assertIn("validate_cuda_toolkit_root()", source)
        self.assertIn("$CUDA_ROOT/bin/nvcc", source)
        self.assertIn("$CUDA_ROOT/include/cuda_runtime.h", source)
        self.assertIn("$CUDA_ROOT/lib64/libcudart.so*", source)
        self.assertIn("Ignoring incomplete CUDA toolkit root", source)

    def test_cuda_build_passes_explicit_cmake_toolkit_and_architecture(self) -> None:
        """CUDA builds should steer CMake away from stale defaults."""
        source = _installer_source()

        self.assertIn("-DCUDAToolkit_ROOT=$CUDA_ROOT", source)
        self.assertIn("-DCMAKE_CUDA_COMPILER=$CUDA_ROOT/bin/nvcc", source)
        self.assertIn("-DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCHS", source)
        self.assertIn("CUDA_CMAKE_ARGS=$(get_cuda_cmake_args", source)
        self.assertIn("GGML_CUDA=1", source)

    def test_backend_menu_does_not_promise_to_install_cuda_toolkit(self) -> None:
        """NVIDIA boxes used to say the CUDA toolkit would be installed.

        install.sh never installs it. Vulkan is tried first; CUDA is a fallback
        only when a complete toolkit is already on the machine.
        """
        source = _installer_source()
        self.assertNotIn("CUDA toolkit will be installed", source)
        self.assertIn("NVIDIA GPU detected (Vulkan)", source)
        self.assertIn('printf "  │     • %-*s│\\n" 54 "$RECOMMENDED_REASON"', source)

    def test_gpu_build_failures_print_pip_log_tail_before_cpu_fallback(self) -> None:
        """Backend failures should expose the real pip/CMake log."""
        source = _installer_source()

        self.assertIn("print_pip_log_tail()", source)
        self.assertIn("Vulkan build failed; checking for NVIDIA GPU to try CUDA", source)
        self.assertIn("CUDA build failed.", source)
        self.assertIn(
            "Continuing with CPU-only pywhispercpp; GPU acceleration is not active.",
            source,
        )

    def test_backend_verification_checks_gpu_libraries_and_cuda_linkage(self) -> None:
        """Do not report GPU support unless native backend libraries exist."""
        source = _installer_source()

        self.assertIn("verify_pywhispercpp_backend_install()", source)
        self.assertIn("libggml-vulkan.so", source)
        self.assertIn("libggml-cuda.so", source)
        self.assertIn("libcuda.so.1", source)
        self.assertIn("libcuda-[^]]+\\.so", source)

    def test_patchelf_remediation_is_attempted_for_bundled_libcuda(self) -> None:
        """Bundled libcuda should trigger patchelf relinking when available."""
        source = _installer_source()

        self.assertIn("patchelf", source)
        self.assertIn("--replace-needed", source)
        self.assertIn("readelf not found", source)

    def test_installer_includes_xsel_for_wayland_clipboard_fallback(self) -> None:
        """Fresh installs should include xsel for ydotool's layout-safe paste path."""
        for distro, config in PACKAGE_MAP.items():
            for tool in ("xclip", "xsel", "wl-clipboard"):
                self.assertTrue(
                    any(
                        package == tool or package.endswith(f"/{tool}")
                        for package in config["system"]
                    ),
                    f"{distro} does not install {tool}",
                )

    def test_optional_apt_package_is_not_in_base_lists(self) -> None:
        """util-linux-extra is probed via apt-cache, not hardcoded in base package lists."""
        source = _installer_source()

        for distro in ("ubuntu", "debian_12", "debian_13_plus"):
            self.assertNotIn("util-linux-extra", PACKAGE_MAP[distro]["system"])
            self.assertIn("util-linux-extra", PACKAGE_MAP[distro]["optional_system"])
        self.assertIn('apt-cache show "$OPTIONAL_PACKAGE"', source)
        self.assertIn('SYSTEM_PACKAGES+=("$OPTIONAL_PACKAGE")', source)


if __name__ == "__main__":
    unittest.main()
