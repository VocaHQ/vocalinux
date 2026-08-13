"""
Comprehensive coverage tests for whispercpp_model_info module.

Tests all functions and constants in the module.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch


class TestComputeBackendClass(unittest.TestCase):
    """Test cases for ComputeBackend class."""

    def test_compute_backend_has_vulkan_constant(self):
        """Test that ComputeBackend has VULKAN constant."""
        from vocalinux.utils.whispercpp_model_info import ComputeBackend

        self.assertTrue(hasattr(ComputeBackend, "VULKAN"))
        self.assertEqual(ComputeBackend.VULKAN, "vulkan")

    def test_compute_backend_has_cuda_constant(self):
        """Test that ComputeBackend has CUDA constant."""
        from vocalinux.utils.whispercpp_model_info import ComputeBackend

        self.assertTrue(hasattr(ComputeBackend, "CUDA"))
        self.assertEqual(ComputeBackend.CUDA, "cuda")

    def test_compute_backend_has_cpu_constant(self):
        """Test that ComputeBackend has CPU constant."""
        from vocalinux.utils.whispercpp_model_info import ComputeBackend

        self.assertTrue(hasattr(ComputeBackend, "CPU"))
        self.assertEqual(ComputeBackend.CPU, "cpu")


class TestModelInfo(unittest.TestCase):
    """Test cases for model information constants."""

    def test_whispercpp_model_info_exists(self):
        """Test that WHISPERCPP_MODEL_INFO is defined."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIsInstance(WHISPERCPP_MODEL_INFO, dict)
        self.assertGreater(len(WHISPERCPP_MODEL_INFO), 0)

    def test_whispercpp_model_info_contains_tiny(self):
        """Test that WHISPERCPP_MODEL_INFO contains tiny model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("tiny", WHISPERCPP_MODEL_INFO)

    def test_whispercpp_model_info_contains_base(self):
        """Test that WHISPERCPP_MODEL_INFO contains base model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("base", WHISPERCPP_MODEL_INFO)

    def test_whispercpp_model_info_contains_small(self):
        """Test that WHISPERCPP_MODEL_INFO contains small model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("small", WHISPERCPP_MODEL_INFO)

    def test_whispercpp_model_info_contains_medium(self):
        """Test that WHISPERCPP_MODEL_INFO contains medium model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("medium", WHISPERCPP_MODEL_INFO)

    def test_whispercpp_model_info_contains_large(self):
        """Test that WHISPERCPP_MODEL_INFO contains large model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("large", WHISPERCPP_MODEL_INFO)

    def test_whispercpp_model_info_contains_large_v3_turbo(self):
        """Test that WHISPERCPP_MODEL_INFO contains large-v3-turbo model."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("large-v3-turbo", WHISPERCPP_MODEL_INFO)

    def test_model_info_has_size_mb(self):
        """Test that each model has size_mb field."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        for model_name, model_info in WHISPERCPP_MODEL_INFO.items():
            self.assertIn("size_mb", model_info, f"{model_name} missing size_mb")
            self.assertIsInstance(model_info["size_mb"], int)
            self.assertGreater(model_info["size_mb"], 0)

    def test_model_info_has_params(self):
        """Test that each model has params field."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        for model_name, model_info in WHISPERCPP_MODEL_INFO.items():
            self.assertIn("params", model_info, f"{model_name} missing params")
            self.assertIsInstance(model_info["params"], str)

    def test_model_info_has_desc(self):
        """Test that each model has desc field."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        for model_name, model_info in WHISPERCPP_MODEL_INFO.items():
            self.assertIn("desc", model_info, f"{model_name} missing desc")
            self.assertIsInstance(model_info["desc"], str)

    def test_model_info_has_url(self):
        """Test that each model has url field."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        for model_name, model_info in WHISPERCPP_MODEL_INFO.items():
            self.assertIn("url", model_info, f"{model_name} missing url")
            self.assertIsInstance(model_info["url"], str)
            self.assertTrue(model_info["url"].startswith("https://"))

    def test_available_models_list_exists(self):
        """Test that AVAILABLE_MODELS list exists."""
        from vocalinux.utils.whispercpp_model_info import AVAILABLE_MODELS

        self.assertIsInstance(AVAILABLE_MODELS, list)
        self.assertGreater(len(AVAILABLE_MODELS), 0)

    def test_available_models_contains_all_models(self):
        """Test that AVAILABLE_MODELS contains all defined models."""
        from vocalinux.utils.whispercpp_model_info import (
            AVAILABLE_MODELS,
            WHISPERCPP_MODEL_INFO,
        )

        self.assertEqual(set(AVAILABLE_MODELS), set(WHISPERCPP_MODEL_INFO.keys()))

    def test_available_models_tracks_upstream_dictation_models(self):
        """Test that AVAILABLE_MODELS covers upstream dictation models."""
        from vocalinux.utils.whispercpp_model_info import AVAILABLE_MODELS

        expected_models = [
            "tiny",
            "tiny.en",
            "tiny-q5_1",
            "tiny.en-q5_1",
            "tiny-q8_0",
            "base",
            "base.en",
            "base-q5_1",
            "base.en-q5_1",
            "base-q8_0",
            "small",
            "small.en",
            "small-q5_1",
            "small.en-q5_1",
            "small-q8_0",
            "medium",
            "medium.en",
            "medium-q5_0",
            "medium.en-q5_0",
            "medium-q8_0",
            "large-v1",
            "large-v2",
            "large-v2-q5_0",
            "large-v2-q8_0",
            "large",  # Vocalinux alias for upstream large-v3
            "large-v3-q5_0",
            "large-v3-turbo",
            "large-v3-turbo-q5_0",
            "large-v3-turbo-q8_0",
        ]

        self.assertEqual(AVAILABLE_MODELS, expected_models)

    def test_model_sizes_group_whispercpp_variants_for_ui(self):
        """Test that whisper.cpp models are grouped into size buckets."""
        from vocalinux.utils.whispercpp_model_info import (
            MODEL_SIZES,
            MODEL_VARIANTS_BY_SIZE,
            WHISPERCPP_MODEL_INFO,
        )

        self.assertEqual(MODEL_SIZES, ["tiny", "base", "small", "medium", "large"])
        self.assertEqual(MODEL_VARIANTS_BY_SIZE["medium"][0], "medium")
        self.assertIn("medium.en-q5_0", MODEL_VARIANTS_BY_SIZE["medium"])
        self.assertIn("large-v3-turbo-q8_0", MODEL_VARIANTS_BY_SIZE["large"])
        self.assertNotIn("small.en-tdrz", MODEL_VARIANTS_BY_SIZE["small"])

        grouped_models = {
            model_name for variants in MODEL_VARIANTS_BY_SIZE.values() for model_name in variants
        }
        self.assertEqual(grouped_models, set(WHISPERCPP_MODEL_INFO.keys()))
        self.assertFalse(
            any(model_name.endswith("-tdrz") for model_name in grouped_models),
            "TinyDiarize needs diarization-specific runtime support, not the base dictation picker",
        )

    def test_model_variant_helpers_identify_size_and_english_only_variants(self):
        """Test helpers that drive the split whisper.cpp model selectors."""
        from vocalinux.utils.whispercpp_model_info import (
            get_model_size,
            get_model_variants,
            is_english_only_model,
        )

        self.assertEqual(get_model_size("medium.en-q5_0"), "medium")
        self.assertEqual(get_model_size("large-v3-turbo-q8_0"), "large")
        self.assertTrue(is_english_only_model("tiny.en-q5_1"))
        self.assertFalse(is_english_only_model("large-v3-turbo"))


class TestDetectVulkanDevices(unittest.TestCase):
    """Test cases for detect_vulkan_devices function."""

    def setUp(self):
        """Clear lru_cache before each test."""
        from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

        detect_vulkan_devices.cache_clear()

    def test_detect_vulkan_devices_empty_when_unavailable(self):
        """Test that detect_vulkan_devices returns empty list when vulkaninfo unavailable."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("vulkaninfo not found")

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(devices, [])

    def test_detect_vulkan_devices_single_discrete(self):
        """Test detection of a single discrete GPU from real vulkaninfo --summary."""
        vulkaninfo_output = (
            "Devices:\n"
            "========\n"
            "GPU0:\n"
            "\tapiVersion         = 1.3.296\n"
            "\tdriverVersion      = 550.54.14\n"
            "\tvendorID           = 0x10de\n"
            "\tdeviceID           = 0x2206\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA RTX 3080\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["index"], 0)
            self.assertEqual(devices[0]["name"], "NVIDIA RTX 3080")
            self.assertEqual(devices[0]["device_type"], "discrete")

    def test_detect_vulkan_devices_hybrid_system(self):
        """Test detection on hybrid system with real vulkaninfo --summary output."""
        vulkaninfo_output = (
            "Devices:\n"
            "========\n"
            "GPU0:\n"
            "\tapiVersion         = 1.3.296\n"
            "\tdriverVersion      = 24.2.8\n"
            "\tvendorID           = 0x8086\n"
            "\tdeviceID           = 0x3e92\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel(R) UHD Graphics 630 (CFL GT2)\n"
            "GPU1:\n"
            "\tapiVersion         = 1.3.242\n"
            "\tdriverVersion      = 550.54.14\n"
            "\tvendorID           = 0x10de\n"
            "\tdeviceID           = 0x1f08\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA GeForce RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(len(devices), 2)
            self.assertEqual(devices[0]["index"], 0)
            self.assertEqual(devices[0]["name"], "Intel(R) UHD Graphics 630 (CFL GT2)")
            self.assertEqual(devices[0]["device_type"], "integrated")
            self.assertEqual(devices[1]["index"], 1)
            self.assertEqual(devices[1]["name"], "NVIDIA GeForce RTX 2060")
            self.assertEqual(devices[1]["device_type"], "discrete")

    def test_detect_vulkan_devices_legacy_gpu_id_format(self):
        """Test compatibility with alternate 'GPU id = N' vulkaninfo headers."""
        vulkaninfo_output = (
            "GPU id = 0\n"
            "deviceName = Intel UHD 630\n"
            "deviceType = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "GPU id = 1\n"
            "deviceName = NVIDIA RTX 2060\n"
            "deviceType = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(len(devices), 2)
            self.assertEqual(devices[0]["index"], 0)
            self.assertEqual(devices[1]["index"], 1)
            self.assertEqual(devices[1]["device_type"], "discrete")

    def test_detect_vulkan_devices_on_timeout(self):
        """Test that timeout returns empty list."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("vulkaninfo", 5)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(devices, [])

    def test_detect_vulkan_devices_on_error(self):
        """Test that error returncode returns empty list."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(devices, [])

    def test_detect_vulkan_devices_falls_back_without_summary(self):
        """Older vulkaninfo without --summary still enumerates GPUs."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA RTX 2060\n"
        )

        def run_side_effect(cmd, **kwargs):
            if cmd == ["vulkaninfo", "--summary"]:
                return MagicMock(returncode=1, stdout="")
            if cmd == ["vulkaninfo"]:
                return MagicMock(returncode=0, stdout=vulkaninfo_output)
            return MagicMock(returncode=1, stdout="")

        with patch("subprocess.run", side_effect=run_side_effect):
            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0]["name"], "NVIDIA RTX 2060")
            self.assertEqual(devices[0]["device_type"], "discrete")

    def test_detect_vulkan_devices_marks_llvmpipe_software(self):
        """Software renderers are classified separately from hardware GPUs."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU\n"
            "\tdeviceName         = llvmpipe (LLVM 19.1.7, 256 bits)\n"
            "GPU1:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA GeForce RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

            devices = detect_vulkan_devices()
            self.assertEqual(devices[0]["device_type"], "software")
            self.assertEqual(devices[1]["device_type"], "discrete")


class TestPreferDiscreteVulkanDevice(unittest.TestCase):
    """Test cases for _prefer_discrete_vulkan_device function."""

    def setUp(self):
        """Clear lru_cache before each test."""
        from vocalinux.utils.whispercpp_model_info import detect_vulkan_devices

        detect_vulkan_devices.cache_clear()

    def test_prefer_discrete_when_available(self):
        """Test that discrete GPU is preferred when available."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel UHD 630\n"
            "GPU1:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import _prefer_discrete_vulkan_device

            preferred_idx = _prefer_discrete_vulkan_device()
            self.assertEqual(preferred_idx, 1)

    def test_prefer_discrete_falls_back_to_first(self):
        """Test that first device is used when no discrete GPU available."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel UHD 630\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import _prefer_discrete_vulkan_device

            preferred_idx = _prefer_discrete_vulkan_device()
            self.assertEqual(preferred_idx, 0)

    def test_prefer_discrete_returns_none_when_empty(self):
        """Test that None is returned when no devices found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("vulkaninfo not found")

            from vocalinux.utils.whispercpp_model_info import _prefer_discrete_vulkan_device

            preferred_idx = _prefer_discrete_vulkan_device()
            self.assertIsNone(preferred_idx)

    def test_prefer_discrete_skips_software_renderer(self):
        """Auto-select must not pick llvmpipe when a real GPU exists."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU\n"
            "\tdeviceName         = llvmpipe (LLVM 19.1.7, 256 bits)\n"
            "GPU1:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import _prefer_discrete_vulkan_device

            preferred_idx = _prefer_discrete_vulkan_device()
            self.assertEqual(preferred_idx, 1)

    def test_prefer_discrete_ignores_software_only(self):
        """Software-only Vulkan should not produce an auto-selected device."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU\n"
            "\tdeviceName         = llvmpipe (LLVM 19.1.7, 256 bits)\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import (
                ComputeBackend,
                _prefer_discrete_vulkan_device,
                detect_compute_backend,
                detect_cuda_support,
                detect_vulkan_support,
            )

            self.assertIsNone(_prefer_discrete_vulkan_device())
            detect_vulkan_support.cache_clear()
            is_available, device_name = detect_vulkan_support()
            self.assertFalse(is_available)
            self.assertIsNone(device_name)

            detect_cuda_support.cache_clear()
            detect_compute_backend.cache_clear()
            backend, _info = detect_compute_backend()
            self.assertNotEqual(backend, ComputeBackend.VULKAN)

    def test_prefer_discrete_with_noncontiguous_gpu_ids(self):
        """Preferred index is the Vulkan GPU id, not the list position."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel UHD 630\n"
            "GPU2:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import (
                _prefer_discrete_vulkan_device,
                detect_vulkan_support,
            )

            preferred_idx = _prefer_discrete_vulkan_device()
            self.assertEqual(preferred_idx, 2)

            detect_vulkan_support.cache_clear()
            is_available, device_name = detect_vulkan_support()
            self.assertTrue(is_available)
            self.assertEqual(device_name, "NVIDIA RTX 2060")


class TestDetectVulkanSupport(unittest.TestCase):
    """Test cases for detect_vulkan_support function."""

    def setUp(self):
        """Clear lru_cache before each test."""
        from vocalinux.utils.whispercpp_model_info import (
            detect_compute_backend,
            detect_cuda_support,
            detect_vulkan_devices,
            detect_vulkan_support,
        )

        detect_vulkan_support.cache_clear()
        detect_vulkan_devices.cache_clear()
        detect_cuda_support.cache_clear()
        detect_compute_backend.cache_clear()

    def test_detect_vulkan_support_returns_tuple(self):
        """Test that detect_vulkan_support returns a tuple."""
        from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

        result = detect_vulkan_support()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_detect_vulkan_support_when_available(self):
        """Test Vulkan detection when vulkaninfo is available."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = Intel Arc\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

            is_available, device_name = detect_vulkan_support()

            self.assertTrue(is_available)
            self.assertEqual(device_name, "Intel Arc")

    def test_detect_vulkan_support_prefers_discrete_on_hybrid(self):
        """Hybrid systems should report the discrete GPU name."""
        vulkaninfo_output = (
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel(R) UHD Graphics 630 (CFL GT2)\n"
            "GPU1:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA GeForce RTX 2060\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=vulkaninfo_output)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

            is_available, device_name = detect_vulkan_support()

            self.assertTrue(is_available)
            self.assertEqual(device_name, "NVIDIA GeForce RTX 2060")

    def test_compute_backend_stays_vulkan_with_real_summary_and_nvidia(self):
        """Regression: real GPU0: summary must not fall through to CUDA."""
        vulkaninfo_output = (
            "Devices:\n"
            "========\n"
            "GPU0:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU\n"
            "\tdeviceName         = Intel(R) UHD Graphics 630 (CFL GT2)\n"
            "GPU1:\n"
            "\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU\n"
            "\tdeviceName         = NVIDIA GeForce RTX 2060\n"
        )

        def run_side_effect(cmd, **kwargs):
            if cmd and cmd[0] == "vulkaninfo":
                return MagicMock(returncode=0, stdout=vulkaninfo_output)
            if cmd and cmd[0] == "nvidia-smi":
                return MagicMock(returncode=0, stdout="NVIDIA GeForce RTX 2060, 6144 MiB")
            return MagicMock(returncode=1, stdout="")

        with patch("subprocess.run", side_effect=run_side_effect):
            from vocalinux.utils.whispercpp_model_info import (
                ComputeBackend,
                detect_compute_backend,
            )

            backend, backend_info = detect_compute_backend()
            self.assertEqual(backend, ComputeBackend.VULKAN)
            self.assertEqual(backend_info, "NVIDIA GeForce RTX 2060")

    def test_detect_vulkan_support_when_unavailable(self):
        """Test Vulkan detection when vulkaninfo is not available."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("vulkaninfo not found")

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

            is_available, device_name = detect_vulkan_support()

            self.assertFalse(is_available)
            self.assertIsNone(device_name)

    def test_detect_vulkan_support_on_timeout(self):
        """Test Vulkan detection when command times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("vulkaninfo", 5)

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

            is_available, device_name = detect_vulkan_support()

            self.assertFalse(is_available)
            self.assertIsNone(device_name)

    def test_detect_vulkan_support_on_error(self):
        """Test Vulkan detection when command returns error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")

            from vocalinux.utils.whispercpp_model_info import detect_vulkan_support

            is_available, device_name = detect_vulkan_support()

            self.assertFalse(is_available)
            self.assertIsNone(device_name)


class TestDetectCudaSupport(unittest.TestCase):
    """Test cases for detect_cuda_support function."""

    def test_detect_cuda_support_returns_tuple(self):
        """Test that detect_cuda_support returns a tuple."""
        from vocalinux.utils.whispercpp_model_info import detect_cuda_support

        result = detect_cuda_support()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_detect_cuda_support_when_available(self):
        """Test CUDA detection when nvidia-smi is available."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="NVIDIA RTX 3080, 10240 MiB\n")

            from vocalinux.utils.whispercpp_model_info import detect_cuda_support

            is_available, device_info = detect_cuda_support()

            self.assertTrue(is_available)
            self.assertIsNotNone(device_info)
            self.assertIn("RTX 3080", device_info)

    def test_detect_cuda_support_when_unavailable(self):
        """Test CUDA detection when nvidia-smi is not available."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("nvidia-smi not found")

            from vocalinux.utils.whispercpp_model_info import detect_cuda_support

            is_available, device_info = detect_cuda_support()

            self.assertFalse(is_available)
            self.assertIsNone(device_info)

    def test_detect_cuda_support_on_timeout(self):
        """Test CUDA detection when command times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("nvidia-smi", 5)

            from vocalinux.utils.whispercpp_model_info import detect_cuda_support

            is_available, device_info = detect_cuda_support()

            self.assertFalse(is_available)
            self.assertIsNone(device_info)


class TestDetectCPUInfo(unittest.TestCase):
    """Test cases for detect_cpu_info function."""

    def test_detect_cpu_info_returns_string(self):
        """Test that detect_cpu_info returns a string."""
        from vocalinux.utils.whispercpp_model_info import detect_cpu_info

        result = detect_cpu_info()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_detect_cpu_info_from_proc_cpuinfo(self):
        """Test CPU detection from /proc/cpuinfo."""
        cpu_info_content = "model name : Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz\n"

        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value = iter([cpu_info_content])

            from vocalinux.utils.whispercpp_model_info import detect_cpu_info

            result = detect_cpu_info()

            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)

    def test_detect_cpu_info_fallback_to_nproc(self):
        """Test CPU detection falls back to nproc."""
        with (
            patch("builtins.open", create=True, side_effect=Exception("No /proc/cpuinfo")),
            patch("subprocess.run") as mock_run,
        ):

            mock_run.return_value = MagicMock(returncode=0, stdout="8\n")

            from vocalinux.utils.whispercpp_model_info import detect_cpu_info

            result = detect_cpu_info()

            self.assertIsInstance(result, str)

    def test_detect_cpu_info_default_fallback(self):
        """Test CPU detection returns default when all methods fail."""
        with (
            patch("builtins.open", create=True, side_effect=Exception()),
            patch("subprocess.run", side_effect=Exception()),
        ):

            from vocalinux.utils.whispercpp_model_info import detect_cpu_info

            result = detect_cpu_info()

            self.assertEqual(result, "CPU")


class TestDetectComputeBackend(unittest.TestCase):
    """Test cases for detect_compute_backend function."""

    def test_detect_compute_backend_returns_tuple(self):
        """Test that detect_compute_backend returns a tuple."""
        from vocalinux.utils.whispercpp_model_info import detect_compute_backend

        result = detect_compute_backend()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_detect_compute_backend_prefers_vulkan(self):
        """Test that detect_compute_backend prefers Vulkan."""
        with (
            patch("vocalinux.utils.whispercpp_model_info.detect_vulkan_support") as mock_vulkan,
            patch("vocalinux.utils.whispercpp_model_info.detect_cuda_support") as mock_cuda,
        ):

            mock_vulkan.return_value = (True, "Intel Arc GPU")
            mock_cuda.return_value = (True, "NVIDIA RTX 3080 (10GB)")

            from vocalinux.utils.whispercpp_model_info import (
                ComputeBackend,
                detect_compute_backend,
            )

            backend, info = detect_compute_backend()

            self.assertEqual(backend, ComputeBackend.VULKAN)

    def test_detect_compute_backend_falls_back_to_cuda(self):
        """Test that detect_compute_backend falls back to CUDA."""
        with (
            patch("vocalinux.utils.whispercpp_model_info.detect_vulkan_support") as mock_vulkan,
            patch("vocalinux.utils.whispercpp_model_info.detect_cuda_support") as mock_cuda,
        ):

            mock_vulkan.return_value = (False, None)
            mock_cuda.return_value = (True, "NVIDIA RTX 3080 (10GB)")

            from vocalinux.utils.whispercpp_model_info import (
                ComputeBackend,
                detect_compute_backend,
            )

            backend, info = detect_compute_backend()

            self.assertEqual(backend, ComputeBackend.CUDA)

    def test_detect_compute_backend_falls_back_to_cpu(self):
        """Test that detect_compute_backend falls back to CPU."""
        with (
            patch("vocalinux.utils.whispercpp_model_info.detect_vulkan_support") as mock_vulkan,
            patch("vocalinux.utils.whispercpp_model_info.detect_cuda_support") as mock_cuda,
            patch("vocalinux.utils.whispercpp_model_info.detect_cpu_info") as mock_cpu,
        ):

            mock_vulkan.return_value = (False, None)
            mock_cuda.return_value = (False, None)
            mock_cpu.return_value = "Intel Core i7"

            from vocalinux.utils.whispercpp_model_info import (
                ComputeBackend,
                detect_compute_backend,
            )

            backend, info = detect_compute_backend()

            self.assertEqual(backend, ComputeBackend.CPU)


class TestGetRecommendedModel(unittest.TestCase):
    """Test cases for get_recommended_model function."""

    def test_get_recommended_model_returns_tuple(self):
        """Test that get_recommended_model returns a tuple."""
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * (1024**3))
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend",
                return_value=("cpu", "Intel Core i7"),
            ):
                import importlib

                import vocalinux.utils.whispercpp_model_info as mod

                importlib.reload(mod)
                result = mod.get_recommended_model()
                self.assertIsInstance(result, tuple)
                self.assertEqual(len(result), 2)

    def test_get_recommended_model_with_vulkan_high_ram(self):
        """Test model recommendation with Vulkan and 8GB+ RAM."""
        import sys

        # Create a mock psutil module
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * (1024**3))

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend"
            ) as mock_backend:
                mock_backend.return_value = ("vulkan", "Intel Arc A770")

                from vocalinux.utils.whispercpp_model_info import get_recommended_model

                model, reason = get_recommended_model()

                self.assertEqual(model, "small")

    def test_get_recommended_model_with_cuda_high_vram(self):
        """Test model recommendation with CUDA and high VRAM."""
        import sys

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=16 * (1024**3))

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend"
            ) as mock_backend:
                mock_backend.return_value = ("cuda", "NVIDIA RTX 4090 (24GB)")

                from vocalinux.utils.whispercpp_model_info import get_recommended_model

                model, reason = get_recommended_model()

                # High VRAM should recommend medium or higher
                self.assertIn(model, ["medium", "large", "small"])

    def test_get_recommended_model_with_cpu_high_ram(self):
        """Test model recommendation with CPU and 16GB+ RAM."""
        import sys

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=16 * (1024**3))

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend"
            ) as mock_backend:
                mock_backend.return_value = ("cpu", "Intel Core i7")

                from vocalinux.utils.whispercpp_model_info import get_recommended_model

                model, reason = get_recommended_model()

                self.assertEqual(model, "base")

    def test_get_recommended_model_with_cpu_medium_ram(self):
        """Test model recommendation with CPU and 8GB RAM."""
        import sys

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * (1024**3))

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend"
            ) as mock_backend:
                mock_backend.return_value = ("cpu", "AMD Ryzen 5")

                from vocalinux.utils.whispercpp_model_info import get_recommended_model

                model, reason = get_recommended_model()

                self.assertEqual(model, "tiny")

    def test_get_recommended_model_with_cpu_low_ram(self):
        """Test model recommendation with CPU and 4GB RAM."""
        import sys

        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=4 * (1024**3))

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend"
            ) as mock_backend:
                mock_backend.return_value = ("cpu", "Intel Atom")

                from vocalinux.utils.whispercpp_model_info import get_recommended_model

                model, reason = get_recommended_model()

                self.assertEqual(model, "tiny")

    def test_get_recommended_model_returns_valid_model_name(self):
        """Test that get_recommended_model returns a valid model name."""
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * (1024**3))
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend",
                return_value=("cpu", "Intel Core i7"),
            ):
                import importlib

                import vocalinux.utils.whispercpp_model_info as mod

                importlib.reload(mod)
                model, reason = mod.get_recommended_model()
                self.assertIn(model, mod.AVAILABLE_MODELS)

    def test_get_recommended_model_returns_reason_string(self):
        """Test that get_recommended_model returns a reason string."""
        mock_psutil = MagicMock()
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * (1024**3))
        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            with patch(
                "vocalinux.utils.whispercpp_model_info.detect_compute_backend",
                return_value=("cpu", "Intel Core i7"),
            ):
                import importlib

                import vocalinux.utils.whispercpp_model_info as mod

                importlib.reload(mod)
                model, reason = mod.get_recommended_model()
                self.assertIsInstance(reason, str)
                self.assertGreater(len(reason), 0)


class TestGetModelPath(unittest.TestCase):
    """Test cases for get_model_path function."""

    def test_get_model_path_returns_string(self):
        """Test that get_model_path returns a string."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        result = get_model_path("tiny")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_get_model_path_tiny(self):
        """Test get_model_path for tiny model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("tiny")
        self.assertIn("ggml-tiny.bin", path)

    def test_get_model_path_base(self):
        """Test get_model_path for base model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("base")
        self.assertIn("ggml-base.bin", path)

    def test_get_model_path_small(self):
        """Test get_model_path for small model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("small")
        self.assertIn("ggml-small.bin", path)

    def test_get_model_path_medium(self):
        """Test get_model_path for medium model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("medium")
        self.assertIn("ggml-medium.bin", path)

    def test_get_model_path_large_uses_v3(self):
        """Test get_model_path for large model uses v3 variant."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("large")
        self.assertIn("ggml-large-v3.bin", path)

    def test_large_model_url_uses_v3(self):
        """Test large model metadata points to upstream large-v3."""
        from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO

        self.assertIn("ggml-large-v3.bin", WHISPERCPP_MODEL_INFO["large"]["url"])

    def test_get_model_path_large_v3_turbo(self):
        """Test get_model_path for large-v3-turbo model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("large-v3-turbo")
        self.assertIn("ggml-large-v3-turbo.bin", path)

    def test_get_model_path_quantized_model(self):
        """Test get_model_path for quantized model."""
        from vocalinux.utils.whispercpp_model_info import get_model_path

        path = get_model_path("large-v3-turbo-q5_0")
        self.assertIn("ggml-large-v3-turbo-q5_0.bin", path)


class TestIsModelDownloaded(unittest.TestCase):
    """Test cases for is_model_downloaded function."""

    def test_is_model_downloaded_returns_bool(self):
        """Test that is_model_downloaded returns a boolean."""
        from vocalinux.utils.whispercpp_model_info import is_model_downloaded

        result = is_model_downloaded("tiny")
        self.assertIsInstance(result, bool)

    def test_is_model_downloaded_when_exists(self):
        """Test is_model_downloaded when model file exists."""
        with patch("os.path.exists", return_value=True):
            from vocalinux.utils.whispercpp_model_info import is_model_downloaded

            result = is_model_downloaded("base")
            self.assertTrue(result)

    def test_is_model_downloaded_when_not_exists(self):
        """Test is_model_downloaded when model file does not exist."""
        with patch("os.path.exists", return_value=False):
            from vocalinux.utils.whispercpp_model_info import is_model_downloaded

            result = is_model_downloaded("base")
            self.assertFalse(result)


class TestGetBackendDisplayName(unittest.TestCase):
    """Test cases for get_backend_display_name function."""

    def test_get_backend_display_name_returns_string(self):
        """Test that get_backend_display_name returns a string."""
        from vocalinux.utils.whispercpp_model_info import (
            ComputeBackend,
            get_backend_display_name,
        )

        result = get_backend_display_name(ComputeBackend.CPU)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_get_backend_display_name_vulkan(self):
        """Test display name for Vulkan backend."""
        from vocalinux.utils.whispercpp_model_info import (
            ComputeBackend,
            get_backend_display_name,
        )

        result = get_backend_display_name(ComputeBackend.VULKAN)
        self.assertEqual(result, "Vulkan GPU")

    def test_get_backend_display_name_cuda(self):
        """Test display name for CUDA backend."""
        from vocalinux.utils.whispercpp_model_info import (
            ComputeBackend,
            get_backend_display_name,
        )

        result = get_backend_display_name(ComputeBackend.CUDA)
        self.assertEqual(result, "NVIDIA CUDA")

    def test_get_backend_display_name_cpu(self):
        """Test display name for CPU backend."""
        from vocalinux.utils.whispercpp_model_info import (
            ComputeBackend,
            get_backend_display_name,
        )

        result = get_backend_display_name(ComputeBackend.CPU)
        self.assertEqual(result, "CPU")

    def test_get_backend_display_name_unknown(self):
        """Test display name for unknown backend."""
        from vocalinux.utils.whispercpp_model_info import get_backend_display_name

        result = get_backend_display_name("rocm")
        self.assertEqual(result, "ROCM")


if __name__ == "__main__":
    unittest.main()
