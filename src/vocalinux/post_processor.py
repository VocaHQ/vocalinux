"""Post-processing of transcribed text via an external executable."""

import logging
import subprocess
from typing import TYPE_CHECKING, Optional

from .utils.host_process import host_env

if TYPE_CHECKING:
    from .ui.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class PostProcessor:
    """Pipes transcribed text through a user-defined executable and returns the output."""

    def __init__(self, script_path: str) -> None:
        self.script_path = script_path

    def process(self, text: str) -> str:
        """Run the script with text on stdin; return stdout. Falls back to original on failure."""
        logger.info("Running post-processor: %s", self.script_path)
        try:
            result = subprocess.run(
                [self.script_path],
                input=text,
                capture_output=True,
                text=True,
                timeout=10,
                env=host_env(),
            )
        except (OSError, subprocess.SubprocessError, UnicodeError) as e:
            logger.warning("Post-processor failed: %s", e)
            return text

        if result.returncode != 0:
            logger.warning("Post-processor exited %d: %s", result.returncode, result.stderr.strip())
            return text

        # Success is logged without the output text: transformed dictation can
        # be sensitive, and logs are retained and exportable.
        logger.debug("Post-processor succeeded, %d bytes out", len(result.stdout))
        return self._strip_convenience_newline(text, result.stdout)

    @staticmethod
    def _strip_convenience_newline(original: str, transformed: str) -> str:
        """Drop one trailing newline a script may add, keeping meaningful ones.

        Line-oriented tools (``echo``, ``print``) terminate their output with a
        newline the input never had; injecting it would press Return after
        every segment. Newlines beyond that — like the ``\\n\\n`` a "new
        paragraph" voice command leaves — are part of the text and stay.
        """
        if transformed.endswith("\n") and not original.endswith("\n"):
            return transformed[:-1]
        return transformed


def apply_post_processing(text: str, config_manager: "ConfigManager") -> Optional[str]:
    """Apply post-processing script to text if configured.

    Returns processed text, or None to signal the caller should skip injection.
    Returns original text unchanged when no script is configured.
    """
    script_path = config_manager.get_str("post_processing", "script_path", "")
    if not script_path:
        return text
    result = PostProcessor(script_path).process(text)
    return result if result else None
