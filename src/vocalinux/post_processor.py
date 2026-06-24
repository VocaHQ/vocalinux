"""Post-processing of transcribed text via an external executable."""

import logging
import subprocess

logger = logging.getLogger(__name__)


class PostProcessor:
    """Pipes transcribed text through a user-defined executable and returns the output."""

    def __init__(self, script_path: str):
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
            )
            if result.returncode != 0:
                logger.warning(
                    "Post-processor exited %d: %s", result.returncode, result.stderr.strip()
                )
                return text
            logger.info("Post-processor returned: %r", result.stdout[:100])
            return result.stdout.rstrip("\n")
        except Exception as e:
            logger.warning("Post-processor failed: %s", e)
            return text


def apply_post_processing(text: str, config_manager) -> "str | None":
    """Apply post-processing script to text if configured.

    Returns processed text, or None to signal the caller should skip injection.
    Returns original text unchanged when no script is configured.
    """
    script_path = config_manager.get_str("post_processing", "script_path", "")
    if not script_path:
        return text
    result = PostProcessor(script_path).process(text)
    return result if result else None
