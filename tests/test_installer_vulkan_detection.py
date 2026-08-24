"""Behavioural tests for the installer's Vulkan detection.

`detect_vulkan` used to accept any non-empty `vulkaninfo --summary` as a GPU, and
read only the first 20 lines while `check_vulkan_gpu_compatibility` read all of
them -- so the wizard could report a GPU in Step 1 and none in Step 3.
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"
SOURCE = INSTALL_SH.read_text()

FUNCTIONS = ("detect_vulkan", "check_vulkan_gpu_compatibility")

PRELUDE = """
set -uo pipefail
HAS_VULKAN="no"
VULKAN_DEVICE=""
print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
"""

# A loader that resolved no driver: header, error, no device.
NO_DEVICES = """\
ERROR: [Loader Message] Code 0 : setup_loader_term_phys_devs: Failed to detect any valid GPUs
==========
VULKANINFO
==========

Vulkan Instance Version: 1.3.239

Instance Extensions: count = 19
Layers: count = 0

Devices:
========
"""

# A real adapter listed past the old `head -20` cutoff.
DEVICE_PAST_LINE_20 = (
    "".join(f"instance preamble line {n}\n" for n in range(1, 25))
    + "\tdeviceName         = AMD Radeon RX 7900 XTX (RADV NAVI31)\n"
)

DEVICE_EARLY = """\
==========
VULKANINFO
==========

Devices:
========
GPU0:
\tdeviceName         = Intel(R) Iris(R) Xe Graphics (TGL GT2)
"""


def _functions() -> str:
    chunks = []
    for name in FUNCTIONS:
        match = re.search(rf"^{name}\(\) \{{.*?^\}}", SOURCE, re.M | re.S)
        assert match, f"{name} not found in install.sh"
        chunks.append(match.group(0))
    return "\n".join(chunks)


# PATH is restricted to these so a real vulkaninfo cannot answer for a stub.
NEEDED_TOOLS = ("awk", "head", "grep", "cut", "tr", "xargs", "sed", "cat")


def _run(tmp_path: Path, summary: str | None, script: str) -> subprocess.CompletedProcess:
    """Run `script` with a stubbed vulkaninfo, or with none at all."""
    binary = tmp_path / "bin"
    binary.mkdir(exist_ok=True)
    for tool in NEEDED_TOOLS:
        found = shutil.which(tool)
        if found and not (binary / tool).exists():
            (binary / tool).symlink_to(found)
    if summary is not None:
        stub = binary / "vulkaninfo"
        stub.write_text(textwrap.dedent("""\
                #!/bin/bash
                case "$1" in
                  --summary) cat <<'SUMMARY'
                {summary}
                SUMMARY
                ;;
                  --features) echo "" ;;
                esac
                """).format(summary=summary.rstrip("\n")))
        stub.chmod(0o755)
    env_path = f'export PATH="{binary}"\n'
    return subprocess.run(
        ["bash", "-c", PRELUDE + env_path + _functions() + "\n" + script],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestDetectVulkan:
    def test_a_loader_without_devices_is_not_a_gpu(self, tmp_path):
        result = _run(
            tmp_path, NO_DEVICES, 'detect_vulkan; echo "RC=$? HAS=$HAS_VULKAN DEV=[$VULKAN_DEVICE]"'
        )
        assert "RC=1 HAS=no DEV=[]" in result.stdout, result.stdout + result.stderr

    def test_it_never_reports_the_fallback_string_as_a_device(self, tmp_path):
        """The old code printed this literal as though it were an adapter name."""
        result = _run(tmp_path, NO_DEVICES, 'detect_vulkan; echo "DEV=[$VULKAN_DEVICE]"')
        assert "Vulkan-compatible GPU" not in result.stdout

    def test_a_device_listed_past_line_20_is_still_found(self, tmp_path):
        result = _run(
            tmp_path,
            DEVICE_PAST_LINE_20,
            'detect_vulkan; echo "HAS=$HAS_VULKAN DEV=[$VULKAN_DEVICE]"',
        )
        assert "HAS=yes" in result.stdout, result.stdout + result.stderr
        assert "DEV=[AMD Radeon RX 7900 XTX (RADV NAVI31)]" in result.stdout

    def test_an_ordinary_device_is_reported_by_name(self, tmp_path):
        result = _run(
            tmp_path, DEVICE_EARLY, 'detect_vulkan; echo "HAS=$HAS_VULKAN DEV=[$VULKAN_DEVICE]"'
        )
        assert "HAS=yes" in result.stdout
        assert "DEV=[Intel(R) Iris(R) Xe Graphics (TGL GT2)]" in result.stdout

    def test_absent_vulkaninfo_is_no(self, tmp_path):
        result = _run(tmp_path, None, 'detect_vulkan; echo "RC=$? HAS=$HAS_VULKAN"')
        assert "RC=1 HAS=no" in result.stdout, result.stdout + result.stderr


class TestTheTwoDetectorsAgree:
    """Both readers must see the same devices, or the wizard contradicts itself."""

    @pytest.mark.parametrize(
        "summary", [NO_DEVICES, DEVICE_PAST_LINE_20, DEVICE_EARLY], ids=["none", "late", "early"]
    )
    def test_a_claimed_gpu_is_a_gpu_the_compat_check_can_see(self, tmp_path, summary):
        result = _run(
            tmp_path,
            summary,
            'detect_vulkan || true; echo "HAS=$HAS_VULKAN"; '
            "check_vulkan_gpu_compatibility || true",
        )
        claimed = "HAS=yes" in result.stdout
        saw_no_devices = "No hardware GPU found" in result.stdout
        assert not (claimed and saw_no_devices), (
            "detect_vulkan announced a GPU that check_vulkan_gpu_compatibility "
            f"cannot find:\n{result.stdout}"
        )
