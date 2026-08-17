"""
Whisper.cpp model information and hardware detection for Vocalinux.

This module provides model metadata and hardware acceleration detection
for whisper.cpp, supporting Vulkan, CUDA, and CPU backends.
"""

import logging
import os
import re
import subprocess
from functools import lru_cache
from typing import Optional

from .paths import is_within_directory, models_dir

logger = logging.getLogger(__name__)

# Whisper.cpp model information
# Models are downloaded from Hugging Face (ggml format)
_WHISPERCPP_REPO_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


def _model_url(model_name: str) -> str:
    """Build the Hugging Face URL for a ggml whisper.cpp model."""
    file_model_name = "large-v3" if model_name == "large" else model_name
    return f"{_WHISPERCPP_REPO_URL}/ggml-{file_model_name}.bin"


_WHISPERCPP_MODEL_SPECS = [
    ("tiny", 74, "39M", "Fastest, lowest accuracy"),
    ("tiny.en", 74, "39M", "English-only tiny model"),
    ("tiny-q5_1", 15, "39M", "Quantized tiny model, lowest memory"),
    ("tiny.en-q5_1", 15, "39M", "Quantized English-only tiny model"),
    ("tiny-q8_0", 32, "39M", "Q8 quantized tiny model"),
    ("base", 141, "74M", "Fast, good for basic use"),
    ("base.en", 141, "74M", "English-only base model"),
    ("base-q5_1", 60, "74M", "Quantized base model, lower memory"),
    ("base.en-q5_1", 60, "74M", "Quantized English-only base model"),
    ("base-q8_0", 82, "74M", "Q8 quantized base model"),
    ("small", 465, "244M", "Balanced speed/accuracy"),
    ("small.en", 465, "244M", "English-only small model"),
    ("small-q5_1", 163, "244M", "Quantized small model, lower memory"),
    ("small.en-q5_1", 163, "244M", "Quantized English-only small model"),
    ("small-q8_0", 190, "244M", "Q8 quantized small model"),
    ("medium", 1463, "769M", "High accuracy, slower"),
    ("medium.en", 1463, "769M", "English-only medium model"),
    ("medium-q5_0", 568, "769M", "Quantized medium model, lower memory"),
    ("medium.en-q5_0", 568, "769M", "Quantized English-only medium model"),
    ("medium-q8_0", 823, "769M", "Q8 quantized medium model"),
    ("large-v1", 2952, "1550M", "Legacy large v1 model"),
    ("large-v2", 2952, "1550M", "Legacy large v2 model"),
    ("large-v2-q5_0", 1170, "1550M", "Quantized large v2 model, lower memory"),
    ("large-v2-q8_0", 1660, "1550M", "Q8 quantized large v2 model"),
    ("large", 2952, "1550M", "Highest accuracy, maps to large v3"),
    ("large-v3-q5_0", 1170, "1550M", "Quantized large v3 model, lower memory"),
    ("large-v3-turbo", 1620, "809M", "High accuracy, lower memory than large"),
    ("large-v3-turbo-q5_0", 574, "809M", "Quantized large v3 Turbo model"),
    ("large-v3-turbo-q8_0", 874, "809M", "Q8 quantized large v3 Turbo model"),
]

WHISPERCPP_MODEL_INFO = {
    spec[0]: {
        "size_mb": spec[1],
        "params": spec[2],
        "desc": spec[3],
        "url": _model_url(spec[0]),
    }
    for spec in _WHISPERCPP_MODEL_SPECS
}

# Available models list
AVAILABLE_MODELS = list(WHISPERCPP_MODEL_INFO.keys())

MODEL_SIZES = ["tiny", "base", "small", "medium", "large"]

MODEL_VARIANTS_BY_SIZE = {
    "tiny": ["tiny", "tiny.en", "tiny-q5_1", "tiny.en-q5_1", "tiny-q8_0"],
    "base": ["base", "base.en", "base-q5_1", "base.en-q5_1", "base-q8_0"],
    "small": [
        "small",
        "small.en",
        "small-q5_1",
        "small.en-q5_1",
        "small-q8_0",
    ],
    "medium": ["medium", "medium.en", "medium-q5_0", "medium.en-q5_0", "medium-q8_0"],
    "large": [
        "large",
        "large-v3-q5_0",
        "large-v3-turbo",
        "large-v3-turbo-q5_0",
        "large-v3-turbo-q8_0",
        "large-v2",
        "large-v2-q5_0",
        "large-v2-q8_0",
        "large-v1",
    ],
}


def get_model_size(model_name: str) -> str:
    """Return the top-level whisper.cpp size bucket for a model variant."""
    model_name = model_name.lower()
    if model_name.startswith("large"):
        return "large"
    return model_name.split(".", 1)[0].split("-", 1)[0]


def get_model_variants(model_size: str) -> list[str]:
    """Return available whisper.cpp variants for a size bucket."""
    return list(MODEL_VARIANTS_BY_SIZE.get(model_size.lower(), []))


def is_english_only_model(model_name: str) -> bool:
    """Return whether a whisper.cpp model variant is English-only."""
    return ".en" in model_name.lower()


# Compute backend types
class ComputeBackend:
    """Compute backend options for whisper.cpp."""

    VULKAN = "vulkan"
    CUDA = "cuda"
    CPU = "cpu"


# Match install.sh: these are not usable whisper.cpp GPUs for auto-select.
_SOFTWARE_VULKAN_NAME_MARKERS = (
    "llvmpipe",
    "swiftshader",
    "lavapipe",
    "zink",
    "virtio",
    "venus",
)

# Real vulkaninfo --summary headers look like "GPU0:"; some older/alternate
# tools print "GPU id = 0". Accept both so hybrid detection does not silently
# fall through to CUDA when Vulkan is present.
_VULKANINFO_GPU_HEADER_RE = re.compile(
    r"^(?:GPU(\d+)\s*:|GPU\s+id\s*[:=]\s*(\d+))\s*$",
    re.IGNORECASE,
)


def _parse_vulkaninfo_gpu_header(line: str) -> Optional[int]:
    """Return a GPU index from a vulkaninfo device header line, if present."""
    match = _VULKANINFO_GPU_HEADER_RE.match(line.strip())
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _is_software_vulkan_name(name: Optional[str]) -> bool:
    """Return True when a Vulkan device name looks like a software renderer."""
    if not name:
        return False
    lowered = name.lower()
    return any(marker in lowered for marker in _SOFTWARE_VULKAN_NAME_MARKERS)


def _classify_vulkan_device_type(type_val: str, name: Optional[str]) -> str:
    """Map vulkaninfo deviceType/name to discrete, integrated, software, or other."""
    if _is_software_vulkan_name(name) or "CPU" in type_val.upper():
        return "software"
    upper = type_val.upper()
    if "DISCRETE" in upper:
        return "discrete"
    if "INTEGRATED" in upper:
        return "integrated"
    return "other"


def _is_software_vulkan_device(device: dict) -> bool:
    """Return True when a parsed Vulkan device should not be auto-selected."""
    return device.get("device_type") == "software" or _is_software_vulkan_name(device.get("name"))


def _hardware_vulkan_devices(devices: Optional[list[dict]] = None) -> list[dict]:
    """Return Vulkan devices that are not software renderers."""
    if devices is None:
        devices = detect_vulkan_devices()
    return [device for device in devices if not _is_software_vulkan_device(device)]


def _append_vulkan_device(
    devices: list[dict],
    current_index: Optional[int],
    current_name: Optional[str],
    current_type: str,
) -> None:
    """Append a parsed Vulkan device when index and name are both known."""
    if current_index is None or current_name is None:
        return
    device_type = current_type
    if _is_software_vulkan_name(current_name):
        device_type = "software"
    devices.append(
        {
            "index": current_index,
            "name": current_name,
            "device_type": device_type,
        }
    )


def _run_vulkaninfo_stdout() -> str:
    """Return vulkaninfo output, falling back when --summary is missing or empty."""
    commands = (["vulkaninfo", "--summary"], ["vulkaninfo"])
    for args in commands:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except FileNotFoundError:
            return ""
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug(f"vulkaninfo {args} failed: {exc}")
            continue

        stdout = result.stdout or ""
        if "deviceName" in stdout or _VULKANINFO_GPU_HEADER_RE.search(stdout):
            return stdout
        if result.returncode == 0 and stdout.strip():
            return stdout
    return ""


@lru_cache(maxsize=1)
def detect_vulkan_devices() -> list[dict]:
    """Enumerate all Vulkan-capable GPU devices.

    Returns:
        List of dicts with keys: index (int), name (str),
        device_type (str: "discrete", "integrated", "software", or "other").
    """
    devices: list[dict] = []
    stdout = _run_vulkaninfo_stdout()
    if not stdout:
        return devices

    current_index = None
    current_name = None
    current_type = "other"

    for line in stdout.split("\n"):
        stripped = line.strip()
        header_index = _parse_vulkaninfo_gpu_header(stripped)

        if header_index is not None:
            _append_vulkan_device(devices, current_index, current_name, current_type)
            current_index = header_index
            current_name = None
            current_type = "other"
            continue

        if "deviceName" in stripped and "=" in stripped:
            current_name = stripped.split("=", 1)[-1].strip()

        if "deviceType" in stripped and "=" in stripped:
            type_val = stripped.split("=", 1)[-1].strip()
            current_type = _classify_vulkan_device_type(type_val, current_name)

    _append_vulkan_device(devices, current_index, current_name, current_type)
    return devices


def _prefer_discrete_vulkan_device() -> Optional[int]:
    """Return the index of the preferred hardware Vulkan GPU (discrete if available)."""
    devices = _hardware_vulkan_devices()
    for device in devices:
        if device["device_type"] == "discrete":
            return device["index"]
    return devices[0]["index"] if devices else None


def _vulkan_device_name_by_index(devices: list[dict], device_index: Optional[int]) -> Optional[str]:
    """Resolve a Vulkan device name by GPU index (not list position)."""
    if not devices:
        return None
    if device_index is None:
        return devices[0]["name"]
    for device in devices:
        if device["index"] == device_index:
            return device["name"]
    return devices[0]["name"]


@lru_cache(maxsize=1)
def detect_vulkan_support() -> tuple[bool, Optional[str]]:
    """Detect if Vulkan is available and get device info.

    When multiple Vulkan GPUs exist, prefers the discrete GPU.

    Returns:
        Tuple of (is_available, device_name)
    """
    devices = detect_vulkan_devices()
    hardware = _hardware_vulkan_devices(devices)
    if hardware:
        preferred_idx = _prefer_discrete_vulkan_device()
        device_name = _vulkan_device_name_by_index(hardware, preferred_idx)
        logger.info(f"Vulkan support detected: {device_name}")
        return True, device_name

    logger.debug("Vulkan detection failed")
    return False, None


@lru_cache(maxsize=1)
def detect_cuda_support() -> tuple[bool, Optional[str]]:
    """
    Detect if NVIDIA CUDA is available and get device info.

    Returns:
        Tuple of (is_available, device_info)
    """
    try:
        # Check for nvidia-smi
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            gpu_info = result.stdout.strip().split(",")
            if gpu_info:
                gpu_name = gpu_info[0].strip()
                gpu_memory = gpu_info[1].strip() if len(gpu_info) > 1 else "unknown"
                logger.info(f"CUDA support detected: {gpu_name} ({gpu_memory})")
                return True, f"{gpu_name} ({gpu_memory})"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"CUDA detection failed: {e}")

    return False, None


@lru_cache(maxsize=1)
def detect_compute_backend() -> tuple[str, str]:
    """
    Detect the best available compute backend.

    Priority order: Vulkan > CUDA > CPU

    Returns:
        Tuple of (backend_type, backend_info)
    """
    # Try Vulkan first (supports AMD, Intel, NVIDIA)
    has_vulkan, vulkan_info = detect_vulkan_support()
    if has_vulkan and vulkan_info:
        return ComputeBackend.VULKAN, vulkan_info

    # Try CUDA next (NVIDIA only)
    has_cuda, cuda_info = detect_cuda_support()
    if has_cuda and cuda_info:
        return ComputeBackend.CUDA, cuda_info

    # Fall back to CPU
    cpu_info = detect_cpu_info()
    return ComputeBackend.CPU, cpu_info


@lru_cache(maxsize=1)
def detect_cpu_info() -> str:
    """
    Detect CPU information for CPU backend.

    Returns:
        CPU info string
    """
    try:
        # Try to get CPU model from /proc/cpuinfo
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    cpu_name = line.split(":")[1].strip()
                    return cpu_name
    except Exception as e:
        logger.debug(f"Could not read CPU info: {e}")

    # Fallback to nproc
    try:
        result = subprocess.run(
            ["nproc"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            cpu_count = result.stdout.strip()
            return f"{cpu_count} cores"
    except Exception:
        pass

    return "CPU"


def get_recommended_model() -> tuple[str, str]:
    """
    Get the recommended whisper.cpp model based on system configuration.

    Returns:
        Tuple of (model_name, reason)
    """
    try:
        import psutil

        ram_gb = psutil.virtual_memory().total // (1024**3)

        # Detect available compute backends
        backend, backend_info = detect_compute_backend()

        if backend == ComputeBackend.VULKAN:
            # Vulkan can handle larger models efficiently
            if ram_gb >= 8:
                return "small", f"Vulkan GPU with {ram_gb}GB RAM"
            else:
                return "base", f"Vulkan GPU with {ram_gb}GB RAM"
        elif backend == ComputeBackend.CUDA:
            # CUDA has more VRAM typically
            if "GB" in backend_info:
                try:
                    vram_gb = int(backend_info.split("GB")[0].split("(")[-1].strip())
                    if vram_gb >= 8:
                        return "medium", f"CUDA GPU with {vram_gb}GB VRAM"
                    elif vram_gb >= 4:
                        return "small", f"CUDA GPU with {vram_gb}GB VRAM"
                    else:
                        return "base", f"CUDA GPU with limited VRAM"
                except (ValueError, IndexError):
                    pass
            return "small", f"CUDA GPU detected"
        else:
            # CPU-only recommendations based on RAM
            if ram_gb >= 16:
                return "base", f"{ram_gb}GB RAM - CPU inference"
            elif ram_gb >= 8:
                return "tiny", f"{ram_gb}GB RAM - optimized for speed"
            else:
                return "tiny", f"Limited RAM ({ram_gb}GB) - fastest model"

    except ImportError:
        logger.debug("psutil not available for system detection")

    # Default recommendation
    return "tiny", "Default recommendation"


def get_model_path(model_name: str) -> str:
    """
    Get the path where a model should be stored.

    Args:
        model_name: Name of the model (for example tiny, base, small, medium, large)

    Returns:
        Path to the model file
    """
    whispercpp_dir = os.path.join(models_dir(), "whispercpp")
    os.makedirs(whispercpp_dir, exist_ok=True)

    model_info = WHISPERCPP_MODEL_INFO.get(model_name)
    if model_info and model_info.get("url"):
        return os.path.join(whispercpp_dir, os.path.basename(model_info["url"]))

    return os.path.join(whispercpp_dir, f"ggml-{model_name}.bin")


def is_model_downloaded(model_name: str) -> bool:
    """
    Check if a whisper.cpp model is downloaded.

    Args:
        model_name: Name of the model

    Returns:
        True if model exists, False otherwise
    """
    model_path = get_model_path(model_name)
    return os.path.exists(model_path)


def list_downloaded_models() -> list[str]:
    """Return catalog model names whose files are present on disk."""
    return [name for name in AVAILABLE_MODELS if is_model_downloaded(name)]


def delete_model(model_name: str) -> str:
    """Delete a downloaded whisper.cpp model file.

    Returns:
        The removed filesystem path.

    Raises:
        ValueError: Unknown model name, or path outside the models directory.
        FileNotFoundError: The model file is not present.
        OSError: The file could not be removed.
    """
    if model_name not in WHISPERCPP_MODEL_INFO:
        raise ValueError(f"Unknown whisper.cpp model: {model_name}")

    model_path = get_model_path(model_name)
    whispercpp_dir = os.path.join(models_dir(), "whispercpp")
    if not is_within_directory(model_path, whispercpp_dir):
        raise ValueError("Refusing to delete a path outside the whisper.cpp models directory")
    if not os.path.isfile(model_path):
        raise FileNotFoundError(model_path)

    os.remove(model_path)
    logger.info("Deleted whisper.cpp model %s (%s)", model_name, model_path)
    return model_path


def get_backend_display_name(backend: str) -> str:
    """
    Get a user-friendly display name for a compute backend.

    Args:
        backend: Backend type (vulkan, cuda, cpu)

    Returns:
        Display name string
    """
    names = {
        ComputeBackend.VULKAN: "Vulkan GPU",
        ComputeBackend.CUDA: "NVIDIA CUDA",
        ComputeBackend.CPU: "CPU",
    }
    return names.get(backend, backend.upper())
