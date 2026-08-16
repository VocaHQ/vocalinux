"""
Settings Dialog for Vocalinux.

Allows users to configure speech recognition engine, model size,
and other relevant parameters.

UX Design Notes:
- Follows GNOME Human Interface Guidelines (HIG) for modern desktop look
- Sidebar navigation (icon + label) with topic-based pages: Dictation,
  Speech Model, Audio, Performance, Application, Advanced
- Live settings search (Ctrl+F) filters rows across all pages in place
- Sidebar footer (always visible from any page): recognition state, mic
  level, a dictation test, and the Close action
- Settings apply immediately when changed (instant-apply pattern)
- In-window Close button for WM compatibility (some WMs hide title bar close)
- Multi-modal feedback (text + icon + audio level) for accessibility
- Modal dialog for model downloads (explicit confirmation for large downloads)
"""

import logging
import os
import re
import threading
import time
from typing import TYPE_CHECKING, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
# Need GLib for idle_add
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from ..common_types import RecognitionState  # noqa: E402
from ..speech_recognition.silero_vad import is_silero_available  # noqa: E402
from ..utils.paths import models_dir  # noqa: E402
from ..utils.update_checker import (  # noqa: E402
    DEFAULT_UPDATE_CHANNEL,
    ReleaseInfo,
    fetch_latest_release,
    format_release_notes,
    is_trusted_release_url,
    is_update_available,
    normalize_channel,
)
from ..utils.vosk_model_info import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    VOSK_MODEL_INFO,
    delete_vosk_model,
    list_downloaded_vosk_models,
    vosk_model_dirname,
)
from ..utils.whispercpp_model_info import MODEL_SIZES as WHISPERCPP_MODEL_SIZES
from ..utils.whispercpp_model_info import (
    WHISPERCPP_MODEL_INFO,
)
from ..utils.whispercpp_model_info import delete_model as delete_whispercpp_model
from ..utils.whispercpp_model_info import (
    detect_compute_backend,
    detect_vulkan_devices,
    get_backend_display_name,
)
from ..utils.whispercpp_model_info import get_model_size as get_whispercpp_model_size
from ..utils.whispercpp_model_info import get_model_variants as get_whispercpp_model_variants
from ..utils.whispercpp_model_info import get_recommended_model as get_recommended_whispercpp_model
from ..utils.whispercpp_model_info import is_english_only_model as is_english_only_whispercpp_model
from ..utils.whispercpp_model_info import is_model_downloaded as is_whispercpp_model_downloaded
from ..utils.whispercpp_model_info import (
    list_downloaded_models as list_downloaded_whispercpp_models,
)
from ..version import __copyright__, __description__, __url__, __version__  # noqa: E402
from .config_manager import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_SOUND_EFFECT_TONE,
    SOUND_EFFECT_TONES,
)
from .keyboard_backends import (  # noqa: E402
    DEFAULT_SHORTCUT,
    DEFAULT_SHORTCUT_MODE,
    SHORTCUT_DISPLAY_NAMES,
    SHORTCUT_GROUPS,
    SHORTCUT_MODES,
    SUPPORTED_SHORTCUTS,
    get_shortcut_display_name,
    is_valid_shortcut,
    parse_shortcut_spec,
)

# Avoid circular imports for type checking
if TYPE_CHECKING:
    from ..speech_recognition.recognition_manager import SpeechRecognitionManager  # noqa: E402
    from .config_manager import ConfigManager  # noqa: E402

logger = logging.getLogger(__name__)


def _raw_audio_device_name(device_name: Optional[str]) -> Optional[str]:
    """Return the persisted device name without UI-only suffixes."""
    if device_name is None:
        return None
    return device_name.removesuffix(" (default)")


def _resolve_audio_device_selection(
    devices: list,
    saved_index: Optional[int],
    saved_name: Optional[str],
) -> Optional[int]:
    """Resolve a saved audio device to a currently listed index.

    Returns the matched device index, or None when the saved device is gone
    (caller should fall back to System Default).
    """
    saved_raw_name = _raw_audio_device_name(saved_name)
    if saved_raw_name:
        for idx, name, _is_default in devices:
            if name == saved_raw_name:
                return idx
    if saved_index is not None:
        for idx, _name, _is_default in devices:
            if idx == saved_index:
                return saved_index
    return None


# Define available models for each engine
ENGINE_MODELS = {
    "vosk": [
        "small",
        "medium",
        "large",
    ],  # Note: 'large' maps to medium internally, as higher version wasn't available
    "whisper": [
        "tiny",
        "base",
        "small",
        "medium",
        "large",
    ],  # Add more whisper sizes if needed
    "whisper_cpp": [
        *WHISPERCPP_MODEL_SIZES,
    ],  # whisper.cpp top-level size buckets; variants are selected separately
    "remote_api": [],  # Remote API does not need local models
}

# Tallest the "Unused downloads" list may grow before it starts scrolling
_UNUSED_DOWNLOADS_MAX_HEIGHT = 220

# Engine display name mapping
ENGINE_DISPLAY_NAMES = {
    "vosk": "Vosk",
    "whisper": "Whisper",
    "whisper_cpp": "whisper.cpp",
    "remote_api": "Remote API",
}


def _engine_display_name(engine: str) -> str:
    """Get the display name of the engine."""
    return ENGINE_DISPLAY_NAMES.get(engine, engine.capitalize())


def _engine_from_display(display_name: str) -> str:
    """Reverse lookup engine ID from display name."""
    for engine_id, name in ENGINE_DISPLAY_NAMES.items():
        if name == display_name:
            return engine_id
    return display_name.lower()


def _model_display_name(model_name: str) -> str:
    """Get a user-friendly model display name."""
    if model_name == "large":
        return "Large v3"

    display_parts = []
    for part in model_name.split("-"):
        if part.endswith(".en"):
            display_parts.append(part[:-3].capitalize())
            display_parts.append("EN")
        elif part.startswith("q"):
            display_parts.append(part.upper())
        elif part == "turbo":
            display_parts.append("Turbo")
        elif part.startswith("v") and part[1:].isdigit():
            display_parts.append(part)
        else:
            display_parts.append(part.capitalize())

    return " ".join(display_parts)


def _model_specialization_display_name(model_name: str) -> str:
    """Get a concise label for a whisper.cpp model variant."""
    if model_name == "large":
        return "Standard v3"

    quantization = None
    for part in model_name.split("-"):
        if part.startswith("q"):
            quantization = part.upper()
            break

    if model_name.startswith("large-v") and "turbo" not in model_name:
        version = next(
            (part for part in model_name.split("-") if part.startswith("v")),
            "large",
        )
        if quantization:
            return f"{version} {quantization}"
        return version

    if is_english_only_whispercpp_model(model_name):
        return f"English-only {quantization}" if quantization else "English-only"

    if "turbo" in model_name:
        if quantization:
            return f"Turbo {quantization}"
        return "Turbo"

    if quantization:
        return f"Quantized {quantization}"

    return "Standard multilingual"


def _language_is_english(language_id: str) -> bool:
    """Return whether a language ID maps to English for Whisper."""
    return SUPPORTED_LANGUAGES.get(language_id, {}).get("whisper") == "en"


def _recommended_whispercpp_variant_for_language(
    recommended_model: str,
    reason: str,
    language_id: str,
) -> tuple[str, str]:
    """Adjust a hardware recommendation to the selected language."""
    recommended_size = get_whispercpp_model_size(recommended_model)
    english_variant = f"{recommended_size}.en"

    if _language_is_english(language_id) and english_variant in WHISPERCPP_MODEL_INFO:
        return english_variant, f"{reason}; English language selected"

    return recommended_model, reason


def _default_whispercpp_variant_for_size(model_size: str, language_id: str) -> Optional[str]:
    """Return the default specialization for a user-selected size and language."""
    variants = get_whispercpp_model_variants(model_size)
    if not variants:
        return None

    english_variant = f"{model_size}.en"
    if _language_is_english(language_id) and english_variant in variants:
        return english_variant

    standard_variant = "large" if model_size == "large" else model_size
    if standard_variant in variants:
        return standard_variant

    return variants[0]


# Uniform width for right-hand row controls so they align down a page
_CONTROL_WIDTH = 230

MODEL_SIZE_TOOLTIP = (
    "Choose the largest model your computer can run comfortably. Tiny/Base are fastest, "
    "Small is balanced, and Medium/Large can be more accurate but need more memory."
)
MODEL_SPECIALIZATION_TOOLTIP = (
    "Choose Standard multilingual unless you specifically need English-only accuracy, "
    "lower-memory quantized models, Turbo speed, or a legacy large model."
)
LANGUAGE_TOOLTIP = (
    "Choose the language you dictate in. Type to search the list. English-only model "
    "specializations limit this list to English."
)


def _model_specialization_tooltip(model_name: str) -> str:
    """Return hover guidance for a whisper.cpp specialization."""
    is_english_only = is_english_only_whispercpp_model(model_name)
    is_quantized = any(part.startswith("q") for part in model_name.split("-"))

    if "turbo" in model_name:
        if is_quantized:
            return (
                "Choose this for a faster large-v3 Turbo model with lower disk and memory use; "
                "expect a small accuracy tradeoff from quantization."
            )
        return (
            "Choose Turbo when you want high accuracy from a large model with less memory use "
            "and faster inference than full large v3."
        )

    if model_name.startswith("large-v") and model_name != "large":
        return (
            "Choose this only if you specifically want that legacy large model version; "
            "Standard v3 or Turbo is the better default for most users."
        )

    if is_english_only and is_quantized:
        return (
            "Choose this for English-only dictation on lower-memory systems; choose "
            "multilingual if you use auto-detect or any non-English language."
        )

    if is_english_only:
        return (
            "Choose this when you dictate only in English. It can be better for English, "
            "but it will not work for other languages."
        )

    if is_quantized:
        return (
            "Choose this on lower-memory systems or when download size matters; it uses "
            "less disk and RAM with a possible accuracy tradeoff."
        )

    if model_name == "large":
        return (
            "Choose Standard v3 when you want the highest default accuracy and have enough "
            "memory for a large model."
        )

    return (
        "Choose Standard multilingual for most users, auto-detect, or any supported "
        "non-English language."
    )


# Whisper model metadata for display
WHISPER_MODEL_INFO = {
    "tiny": {"size_mb": 75, "desc": "Fastest, lowest accuracy", "params": "39M"},
    "base": {"size_mb": 142, "desc": "Fast, good for basic use", "params": "74M"},
    "small": {"size_mb": 466, "desc": "Balanced speed/accuracy", "params": "244M"},
    "medium": {"size_mb": 1500, "desc": "High accuracy, slower", "params": "769M"},
    "large": {"size_mb": 2900, "desc": "Highest accuracy, slowest", "params": "1550M"},
}


def get_available_engines():
    """
    Detect which speech recognition engines are available/installed.
    Returns a dictionary of engine_name -> availability (bool).
    """
    engines = {"vosk": False, "whisper": False, "whisper_cpp": False, "remote_api": False}

    # Check VOSK
    try:
        import vosk

        engines["vosk"] = True
    except ImportError:
        pass

    # Check OpenAI Whisper
    try:
        import whisper

        engines["whisper"] = True
    except ImportError:
        pass

    # Check whisper.cpp (pywhispercpp)
    try:
        from pywhispercpp.model import Model

        engines["whisper_cpp"] = True
    except ImportError:
        pass

    # Remote API is always available (only requires requests package)
    try:
        import requests  # noqa: F401

        engines["remote_api"] = True
    except ImportError:
        pass

    logger.debug(f"Available engines: {engines}")
    return engines


# Models directory
MODELS_DIR = models_dir()
SYSTEM_MODELS_DIRS = [
    "/usr/local/share/vocalinux/models",
    "/usr/share/vocalinux/models",
]

# CSS for modern styling
SETTINGS_CSS = """
/* Sidebar navigation (GNOME Settings style) */
.settings-sidebar {
    background-color: alpha(@theme_bg_color, 0.5);
    border-right: 1px solid alpha(@borders, 0.5);
}

.settings-sidebar list {
    background-color: transparent;
}

.sidebar-row {
    padding: 10px 12px;
    border-radius: 8px;
    margin: 1px 6px;
}

.sidebar-row:hover {
    background-color: alpha(@theme_fg_color, 0.07);
}

.sidebar-row:selected {
    background-color: alpha(@theme_selected_bg_color, 0.85);
    color: @theme_selected_fg_color;
}

.sidebar-row label {
    font-weight: 500;
    font-size: 0.95em;
}

.sidebar-match-count {
    font-size: 0.8em;
    color: @theme_unfocused_fg_color;
    background-color: alpha(@theme_fg_color, 0.1);
    border-radius: 10px;
    padding: 1px 7px;
}

.sidebar-row:selected .sidebar-match-count {
    color: @theme_selected_fg_color;
    background-color: alpha(@theme_selected_fg_color, 0.2);
}

.sidebar-update-badge {
    font-size: 0.75em;
    font-weight: 600;
    color: #ffffff;
    background-color: #26a269;
    border-radius: 10px;
    padding: 1px 7px;
}

.settings-search {
    margin: 8px 6px 14px 6px;
    border-radius: 8px;
}

/* Sidebar footer: dictation status, test action, and dialog close */
.sidebar-footer {
    padding: 10px 6px 12px 6px;
}

.sidebar-footer button {
    min-height: 30px;
    border-radius: 8px;
}

/* Empty search results */
.search-empty-title {
    font-size: 1.1em;
    font-weight: bold;
    color: @theme_unfocused_fg_color;
}

/* Recognition state label in the sidebar footer */
.status-strip-state {
    font-weight: 500;
    font-size: 0.9em;
}

/* Modern GNOME-style settings dialog */
.settings-dialog {
    background-color: @theme_bg_color;
}

/* Preference group styling - card-like appearance */
.preferences-group {
    background-color: @theme_base_color;
    border-radius: 12px;
    padding: 0;
    margin: 6px 0;
    border: 1px solid alpha(@borders, 0.5);
}

.preferences-group-title {
    font-weight: bold;
    font-size: 0.9em;
    color: @theme_unfocused_fg_color;
    padding: 12px 16px 6px 16px;
    margin: 0;
}

/* Row styling */
.preference-row {
    padding: 12px 16px;
    min-height: 32px;
    border-bottom: 1px solid alpha(@borders, 0.3);
}

.preference-row:last-child {
    border-bottom: none;
}

.preference-row:hover {
    background-color: alpha(@theme_selected_bg_color, 0.1);
}

.preference-row-title {
    font-weight: 500;
}

.preference-row-subtitle {
    font-size: 0.85em;
    color: @theme_unfocused_fg_color;
}

/* Status indicators */
.status-success {
    color: #26a269;
}

.status-warning {
    color: #e5a50a;
}

.status-error {
    color: #c01c28;
}

.status-info {
    color: @theme_unfocused_fg_color;
}

/* Test area styling */
.test-area {
    background-color: @theme_base_color;
    border-radius: 8px;
    padding: 12px;
    border: 1px solid alpha(@borders, 0.5);
}

.test-textview {
    font-family: monospace;
    font-size: 0.95em;
    padding: 8px;
    background-color: alpha(@theme_bg_color, 0.5);
    border-radius: 6px;
}

/* Level bars */
levelbar block.filled {
    background-color: @theme_selected_bg_color;
    border-radius: 3px;
}

levelbar block.empty {
    background-color: alpha(@theme_fg_color, 0.1);
    border-radius: 3px;
}

/* Combo boxes and spin buttons */
combobox button,
combobox entry,
spinbutton {
    min-height: 32px;
    border-radius: 6px;
}

/* Section headers */
.section-header {
    font-size: 1.1em;
    font-weight: bold;
    margin-top: 12px;
    margin-bottom: 6px;
}

/* Flat helper notices — muted surface, no accent strip */
.info-box {
    background-color: alpha(@theme_fg_color, 0.04);
    border: 1px solid alpha(@borders, 0.45);
    border-radius: 8px;
    padding: 10px 12px;
}

.info-box image {
    opacity: 0.55;
}

.info-box-warning {
    background-color: alpha(#e5a50a, 0.08);
    border-color: alpha(#e5a50a, 0.4);
}

/* Recognition status */
.recognition-idle {
    color: @theme_unfocused_fg_color;
}

.recognition-listening {
    color: #26a269;
}

.recognition-processing {
    color: #e5a50a;
}

.recognition-error {
    color: #c01c28;
}

/* Buttons */
.suggested-action {
    background-color: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
}

.flat-button {
    background: transparent;
    border: none;
    padding: 8px;
    border-radius: 6px;
}

.flat-button:hover {
    background-color: alpha(@theme_fg_color, 0.1);
}

/* Scrolled content */
.scrolled-content {
    background-color: transparent;
}

/* Model info card */
.model-info-card {
    background-color: alpha(@theme_base_color, 0.8);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 8px 0;
}

.model-info-title {
    font-weight: bold;
    font-size: 1.0em;
}

/* Unused downloads: one collapsed row until expanded */
.unused-downloads-expander {
    padding: 8px 12px;
}

.unused-downloads-expander list {
    background-color: transparent;
}

.model-info-subtitle {
    font-size: 0.9em;
    color: @theme_unfocused_fg_color;
}

/* Tip styling */
.tip-label {
    font-size: 0.85em;
    color: @theme_unfocused_fg_color;
    font-style: italic;
}

.tip-highlight {
    font-weight: bold;
    color: @theme_selected_bg_color;
}
"""


def _setup_css():
    """Set up CSS styling for the settings dialog."""
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(SETTINGS_CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def _prevent_scroll_on_hover(widget: Gtk.Widget):
    """
    Prevent scroll events from modifying widget values when hovering.

    Unfocused ComboBox/SpinButton widgets ignore wheel input so scrolling a
    settings tab does not accidentally change values. The event is applied to
    the nearest ancestor ScrolledWindow instead, so the page still scrolls.
    """

    def on_scroll(widget, event):
        if widget.has_focus():
            return False
        scrolled = widget.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is not None:
            scrolled.event(event)
        return True

    widget.connect("scroll-event", on_scroll)
    widget.set_can_focus(True)


def _combo_text_matches_query(query: str, item_id: str, item_text: str) -> bool:
    """Return whether a combo row matches a case-insensitive search query."""
    needle = (query or "").strip().lower()
    if not needle:
        return True
    return needle in (item_text or "").lower() or needle in (item_id or "").lower()


def _resolve_combo_text_query(query: str, rows: list) -> Optional[str]:
    """Return a unique matching combo id, preferring an exact name or id."""
    needle = (query or "").strip()
    if not needle:
        return None
    needle_l = needle.lower()
    matches = []
    for item_id, item_text in rows:
        item_id = item_id or ""
        item_text = item_text or ""
        if item_text.lower() == needle_l or item_id.lower() == needle_l:
            return item_id
        if _combo_text_matches_query(needle, item_id, item_text):
            matches.append(item_id)
    if len(matches) == 1:
        return matches[0]
    return None


def _combo_text_rows(combo: Gtk.ComboBoxText) -> list:
    """Return ``(id, display text)`` pairs from a ComboBoxText model.

    Gtk.ComboBoxText stores display text in column 0 and the id in column 1.
    """
    model = combo.get_model()
    if not model:
        return []
    return [(row[1], row[0]) for row in model]


def _combo_completion_match(completion, key, tree_iter, *_args) -> bool:
    """GtkEntryCompletion match function for ComboBoxText text/id columns."""
    model = completion.get_model()
    if model is None:
        return False
    row = model[tree_iter]
    return _combo_text_matches_query(key, row[1], row[0])


def _attach_language_combo_search(combo: Gtk.ComboBoxText) -> None:
    """Filter language choices as the user types in a ComboBoxText entry."""
    entry = combo.get_child()
    if entry is None:
        return
    entry.set_placeholder_text("Search languages…")
    completion = Gtk.EntryCompletion()
    completion.set_model(combo.get_model())
    # ComboBoxText store: column 0 is display text, column 1 is id.
    completion.set_text_column(0)
    completion.set_inline_completion(False)
    completion.set_popup_completion(True)
    completion.set_minimum_key_length(1)
    completion.set_match_func(_combo_completion_match)
    entry.set_completion(completion)


def _get_whisper_cache_dir() -> str:
    """Get the Whisper model cache directory."""
    return os.path.join(MODELS_DIR, "whisper")


def _whisper_model_files(model_name: str) -> list[str]:
    """Return existing OpenAI Whisper weight files for a catalog model name."""
    if model_name not in WHISPER_MODEL_INFO:
        return []

    filename = f"{model_name}.pt"
    candidates = [
        os.path.join(_get_whisper_cache_dir(), filename),
        os.path.join(os.path.expanduser("~/.cache/whisper"), filename),
    ]
    allowed_parents = {
        os.path.realpath(_get_whisper_cache_dir()),
        os.path.realpath(os.path.expanduser("~/.cache/whisper")),
    }

    found: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        real = os.path.realpath(candidate)
        if real in seen or os.path.dirname(real) not in allowed_parents:
            continue
        if os.path.basename(real) != filename:
            continue
        seen.add(real)
        found.append(real)
    return found


def _is_whisper_model_downloaded(model_name: str) -> bool:
    """Check if a Whisper model is downloaded."""
    cache_dir = _get_whisper_cache_dir()
    model_file = os.path.join(cache_dir, f"{model_name}.pt")
    if os.path.exists(model_file):
        return True
    # Also check default whisper cache
    default_cache = os.path.expanduser("~/.cache/whisper")
    return os.path.exists(os.path.join(default_cache, f"{model_name}.pt"))


def _list_downloaded_whisper_models() -> list[str]:
    """Return OpenAI Whisper catalog names that are present on disk."""
    return [name for name in WHISPER_MODEL_INFO if _is_whisper_model_downloaded(name)]


def _delete_whisper_model(model_name: str) -> list[str]:
    """Delete OpenAI Whisper weight files for a catalog model name."""
    if model_name not in WHISPER_MODEL_INFO:
        raise ValueError(f"Unknown Whisper model: {model_name}")

    files = _whisper_model_files(model_name)
    if not files:
        raise FileNotFoundError(model_name)

    for path in files:
        os.remove(path)
        logger.info("Deleted Whisper model %s (%s)", model_name, path)
    return files


def _format_size(size_mb: int) -> str:
    """Format size in MB to human readable string."""
    if size_mb >= 1000:
        return f"{size_mb / 1000:.1f} GB"
    return f"{size_mb} MB"


def _get_recommended_whisper_model() -> tuple:
    """Get recommended model based on system configuration."""
    import warnings

    try:
        import psutil

        ram_gb = psutil.virtual_memory().total // (1024**3)

        # Check for CUDA - suppress warnings during detection
        has_cuda = False
        cuda_memory_gb = 0
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import torch

                if torch.cuda.is_available():
                    has_cuda = True
                    cuda_memory_gb = torch.cuda.get_device_properties(0).total_memory // (1024**3)
        except Exception:
            pass

        if has_cuda and cuda_memory_gb >= 8:
            return "medium", f"GPU with {cuda_memory_gb}GB VRAM"
        elif has_cuda and cuda_memory_gb >= 4:
            return "small", f"GPU with {cuda_memory_gb}GB VRAM"
        elif ram_gb >= 8:
            return "small", f"{ram_gb}GB RAM - good balance"
        elif ram_gb >= 4:
            return "base", f"{ram_gb}GB RAM"
        else:
            return "tiny", f"Limited RAM ({ram_gb}GB)"
    except Exception:
        return "base", "Default recommendation"


def _is_vosk_model_downloaded(size: str, language: str) -> bool:
    """Check if a VOSK model is downloaded."""
    if size not in VOSK_MODEL_INFO:
        return False

    # Auto-detect is not supported by VOSK, fall back to en-us
    if language == "auto" or language not in VOSK_MODEL_INFO[size]["languages"]:
        language = "en-us"

    model_name = VOSK_MODEL_INFO[size]["languages"][language]

    # Check user's local models directory
    user_model_path = os.path.join(MODELS_DIR, model_name)
    if os.path.exists(user_model_path):
        return True

    # Check system-wide installation directories
    for system_dir in SYSTEM_MODELS_DIRS:
        system_model_path = os.path.join(system_dir, model_name)
        if os.path.exists(system_model_path):
            return True

    return False


def _get_recommended_vosk_model() -> tuple:
    """Get recommended VOSK model based on system configuration."""
    try:
        import psutil

        ram_gb = psutil.virtual_memory().total // (1024**3)

        # VOSK models are CPU-based, so we recommend based on RAM and disk space
        if ram_gb >= 4:
            return "medium", f"{ram_gb}GB RAM - better accuracy"
        else:
            return "small", f"Limited RAM ({ram_gb}GB) - optimized for speed"
    except Exception:
        return "small", "Default recommendation"


# GDK key-symbol names that are themselves modifiers (skipped while recording).
_GDK_MODIFIER_KEYNAMES = {
    "Control_L",
    "Control_R",
    "Alt_L",
    "Alt_R",
    "Shift_L",
    "Shift_R",
    "Super_L",
    "Super_R",
    "Meta_L",
    "Meta_R",
    "Hyper_L",
    "Hyper_R",
    "ISO_Level3_Shift",
}

# GDK key-symbol names -> canonical main-key tokens (irregular names only;
# single letters/digits and function keys are handled by rule).
_GDK_KEYNAME_TOKENS = {
    "space": "space",
    "Return": "enter",
    "KP_Enter": "enter",
    "Tab": "tab",
    "Escape": "esc",
    "BackSpace": "backspace",
    "Delete": "delete",
    "Insert": "insert",
    "Home": "home",
    "End": "end",
    "Page_Up": "pageup",
    "Page_Down": "pagedown",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "comma": "comma",
    "period": "period",
    "slash": "slash",
    "semicolon": "semicolon",
    "apostrophe": "apostrophe",
    "grave": "grave",
    "minus": "minus",
    "equal": "equal",
    "bracketleft": "leftbracket",
    "bracketright": "rightbracket",
    "backslash": "backslash",
}


def _gdk_keyname_to_token(name: Optional[str]) -> Optional[str]:
    """Map a GDK keyval name to a canonical main-key token, or None."""
    if not name:
        return None
    if name in _GDK_KEYNAME_TOKENS:
        return _GDK_KEYNAME_TOKENS[name]
    if len(name) == 1 and name.isalnum():
        return name.lower()
    if re.fullmatch(r"[Ff]([1-9]|1[0-9]|2[0-4])", name):
        return name.lower()
    return None


def _row_matches_query(query: str, title: str, subtitle: str = "", keywords=()) -> bool:
    """Return whether a settings row matches a search query.

    Matching is case-insensitive and checks the row title, subtitle, and any
    extra keywords attached to the row.
    """
    query = (query or "").strip().casefold()
    if not query:
        return True
    haystacks = [title or "", subtitle or "", *keywords]
    return any(query in text.casefold() for text in haystacks)


class PreferencesGroup(Gtk.Box):
    """A card-style group of preferences, similar to libadwaita's AdwPreferencesGroup."""

    def __init__(
        self,
        title: str = "",
        description: str = "",
        keywords=(),
        header_icon: Optional[Gtk.Widget] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("preferences-group")
        self.title = title
        self.description = description
        self.keywords = tuple(keywords)
        self.rows = []

        # Header with title (optional icon aligned to the top-right)
        if title:
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            title_label = Gtk.Label(label=title, xalign=0)
            title_label.get_style_context().add_class("preferences-group-title")
            text_box.pack_start(title_label, False, False, 0)

            if description:
                desc_label = Gtk.Label(label=description, xalign=0, wrap=True)
                desc_label.get_style_context().add_class("preference-row-subtitle")
                # Align with the title, which carries 16px CSS padding.
                desc_label.set_margin_start(16)
                desc_label.set_margin_end(16)
                text_box.pack_start(desc_label, False, False, 0)

            if header_icon is not None:
                header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                header_box.set_margin_top(12)
                header_box.set_margin_bottom(4)
                header_box.set_margin_start(16)
                header_box.set_margin_end(16)
                header_box.pack_start(text_box, True, True, 0)
                header_icon.set_valign(Gtk.Align.CENTER)
                header_box.pack_end(header_icon, False, False, 0)
            else:
                header_box = text_box
                header_box.set_margin_top(12)
                header_box.set_margin_bottom(4)
                header_box.set_margin_start(16)
                header_box.set_margin_end(16)

            self.pack_start(header_box, False, False, 0)

        # Content area with listbox for rows
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_activate_on_single_click(False)
        self.pack_start(self.listbox, False, False, 0)

    def add_row(self, widget):
        """Add a widget as a row in the preferences group."""
        self.listbox.add(widget)
        self.rows.append(widget)

    def clear_rows(self):
        """Remove all preference rows from the group."""
        for row in list(self.listbox.get_children()):
            self.listbox.remove(row)
        self.rows.clear()


class PreferenceRow(Gtk.ListBoxRow):
    """A single preference row with title, subtitle, and a control widget."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        widget: Gtk.Widget = None,
        activatable: bool = False,
        keywords=(),
    ):
        super().__init__()
        self.set_activatable(activatable)
        self.get_style_context().add_class("preference-row")
        self.title = title
        self.subtitle = subtitle
        self.keywords = tuple(keywords)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox.set_margin_top(12)
        hbox.set_margin_bottom(12)
        hbox.set_margin_start(16)
        hbox.set_margin_end(16)

        # Text container (title + subtitle)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.get_style_context().add_class("preference-row-title")
        text_box.pack_start(title_label, False, False, 0)

        # Store subtitle label reference for later updates
        self.subtitle_label = None
        if subtitle:
            self.subtitle_label = Gtk.Label(label=subtitle, xalign=0, wrap=True)
            self.subtitle_label.get_style_context().add_class("preference-row-subtitle")
            self.subtitle_label.set_max_width_chars(55)
            self.subtitle_label.set_line_wrap(True)
            self.subtitle_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text_box.pack_start(self.subtitle_label, False, False, 0)

        hbox.pack_start(text_box, True, True, 0)

        # Control widget on the right
        if widget:
            widget.set_valign(Gtk.Align.CENTER)
            hbox.pack_end(widget, False, False, 0)

        self.add(hbox)

    def set_subtitle(self, subtitle: str):
        """Update the subtitle text."""
        self.subtitle = subtitle
        if self.subtitle_label:
            self.subtitle_label.set_text(subtitle)

    def matches_query(self, query: str) -> bool:
        """Return whether this row matches a settings search query."""
        return _row_matches_query(query, self.title, self.subtitle, self.keywords)


class SettingsPage:
    """One topic page in the settings dialog (sidebar entry + stack child).

    Wraps the page content box and, after the page is built, records which
    children are searchable PreferencesGroups vs. loose "extra" widgets
    (info boxes, status labels) that are simply hidden while searching.
    """

    def __init__(self, name: str, title: str, icon_name: str):
        self.name = name
        self.title = title
        self.icon_name = icon_name
        self.groups = []
        self.extras = []
        self.sidebar_row = None
        self.match_count_label = None
        self.update_badge_label = None

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.box.set_margin_top(16)
        self.box.set_margin_bottom(16)
        self.box.set_margin_start(16)
        self.box.set_margin_end(16)

    def collect_children(self):
        """Classify built descendants into searchable groups and extras.

        Most groups are direct page children, but gated sections such as the
        Advanced decoding controls live inside a Gtk.Revealer. Walk nested
        containers so unlocked settings are searchable too.
        """
        self.groups = []
        self.extras = []

        def collect_groups(widget):
            if isinstance(widget, PreferencesGroup):
                self.groups.append(widget)
                return True
            if isinstance(widget, Gtk.Container):
                found = False
                for child in widget.get_children():
                    found = collect_groups(child) or found
                return found
            return False

        for child in self.box.get_children():
            if not collect_groups(child):
                self.extras.append(child)


class ModelDownloadDialog(Gtk.Dialog):
    """Dialog showing model download progress with cancel support."""

    def __init__(
        self,
        parent,
        model_name: str,
        model_size_mb: int,
        engine: str = "whisper",
        language: str = "en-us",
    ):
        super().__init__(
            title=f"Downloading {_model_display_name(model_name)} Model",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL,
        )
        self.set_default_size(450, 200)
        self.set_deletable(False)  # Prevent closing during download

        self.cancelled = False
        self.engine = engine
        self.model_name = model_name

        engine_display = engine.upper() if engine == "vosk" else engine.capitalize()

        box = self.get_content_area()
        box.set_spacing(16)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_margin_top(24)
        box.set_margin_bottom(20)

        # Info label
        self.info_label = Gtk.Label(
            label=(
                f"Downloading {engine_display} {_model_display_name(model_name)} model "
                f"(~{_format_size(model_size_mb)})..."
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        box.pack_start(self.info_label, False, False, 0)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text("Connecting...")
        box.pack_start(self.progress_bar, False, False, 8)

        # Status label (shows speed and ETA)
        self.status_label = Gtk.Label(label="")
        self.status_label.set_markup("<i>Please wait...</i>")
        self.status_label.get_style_context().add_class("status-info")
        box.pack_start(self.status_label, False, False, 0)

        # Cancel button
        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", self._on_cancel_clicked)
        self.cancel_button.set_halign(Gtk.Align.CENTER)
        self.cancel_button.set_margin_top(12)
        box.pack_start(self.cancel_button, False, False, 0)

        self.show_all()

        # For Whisper, we can't track progress, so pulse
        if engine == "whisper":
            self._pulse_timeout = GLib.timeout_add(100, self._pulse_progress)
        else:
            self._pulse_timeout = None

    def _pulse_progress(self):
        """Pulse the progress bar while downloading (for Whisper)."""
        if self.cancelled:
            return False
        self.progress_bar.pulse()
        return True  # Continue pulsing

    def _on_cancel_clicked(self, widget):
        """Handle cancel button click."""
        self.cancelled = True
        self.cancel_button.set_sensitive(False)
        self.cancel_button.set_label("Cancelling...")
        self.status_label.set_markup("<i>Cancelling download...</i>")

    def update_progress(self, fraction: float, speed_mbps: float, status_text: str):
        """Update the progress bar with actual download progress."""
        if self.cancelled:
            return

        # Stop pulsing if we were pulsing
        if self._pulse_timeout:
            GLib.source_remove(self._pulse_timeout)
            self._pulse_timeout = None

        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(f"{fraction * 100:.0f}%")
        self.status_label.set_markup(f"<i>{status_text}</i>")

    def set_complete(self, success: bool, message: str = ""):
        """Mark download as complete."""
        if self._pulse_timeout:
            GLib.source_remove(self._pulse_timeout)
            self._pulse_timeout = None

        # Hide cancel button
        self.cancel_button.hide()

        if success:
            self.progress_bar.set_fraction(1.0)
            self.progress_bar.set_text("Complete!")
            self.status_label.set_markup(
                "<span foreground='#26a269'><b>✓ Model ready to use</b></span>"
            )
        else:
            self.progress_bar.set_fraction(0)
            self.progress_bar.set_text("Failed")
            if "cancelled" in message.lower():
                self.status_label.set_markup(
                    "<span foreground='#e5a50a'>✗ Download cancelled</span>"
                )
            else:
                self.status_label.set_markup(f"<span foreground='#c01c28'>✗ {message}</span>")

        # Allow closing now
        self.set_deletable(True)
        self.add_button("OK", Gtk.ResponseType.OK)


class SettingsDialog(Gtk.Dialog):
    """Modern GTK Dialog for configuring Vocalinux settings."""

    def __init__(
        self,
        parent: Gtk.Window,
        config_manager: "ConfigManager",
        speech_engine: "SpeechRecognitionManager",
        shortcut_update_callback: callable = None,
        initial_page: Optional[str] = None,
        pending_update: Optional[ReleaseInfo] = None,
        update_status_callback: callable = None,
    ):
        super().__init__(title="Vocalinux Settings", transient_for=parent, flags=0)
        # Force window decorations (title-bar close) on all WMs. An in-window
        # Close button also lives in the sidebar footer so the dialog always
        # has a visible way to dismiss it, even on window managers that hide
        # the title-bar close button for Gtk.Dialog windows (fixes #323).
        self.set_decorated(True)

        self.config_manager = config_manager
        self.speech_engine = speech_engine
        self.shortcut_update_callback = shortcut_update_callback
        self.update_status_callback = update_status_callback
        self._test_active = False
        self._test_result = ""
        self._initializing = True  # Flag to prevent auto-apply during initialization
        self._populating_models = False  # Flag to prevent model change handler during population
        self._processing_language_change = (
            False  # Flag to prevent recursive language change handling
        )
        self._applying_settings = False  # Flag to prevent recursive settings application
        self._advanced_prompt_dirty = False
        self._about_release_url = ""
        self._update_check_in_progress = False
        self._update_check_generation = 0
        self._update_auto_checked = False
        self._initial_page = initial_page
        self._pending_update = pending_update

        # Setup CSS styling
        _setup_css()

        # Dialog configuration - Close button lives in the sidebar footer (see #323)
        # Calculate dialog size
        display = Gdk.Display.get_default()
        if display:
            monitor = display.get_primary_monitor()
            if not monitor and display.get_n_monitors() > 0:
                monitor = display.get_monitor(0)
            if monitor:
                geometry = monitor.get_geometry()
                screen_height = geometry.height
                screen_width = geometry.width
            else:
                screen_height = 1080  # Default fallback
                screen_width = 1920
        else:
            screen_height = 1080  # Default fallback
            screen_width = 1920
        dialog_height = min(760, int(screen_height * 0.8))
        dialog_width = min(880, int(screen_width * 0.85))
        self.set_default_size(dialog_width, dialog_height)
        self.get_style_context().add_class("settings-dialog")

        # Topic-based pages (GNOME HIG: group by topic, navigate via sidebar)
        # Icons stick to the stock Adwaita symbolic set so they resolve on
        # every distro (some system-monitor icons only ship with Yaru).
        self._pages = [
            SettingsPage("dictation", "Dictation", "input-keyboard-symbolic"),
            SettingsPage("model", "Speech Model", "audio-input-microphone-symbolic"),
            SettingsPage("audio", "Audio", "audio-speakers-symbolic"),
            SettingsPage("performance", "Performance", "power-profile-performance-symbolic"),
            SettingsPage("application", "Application", "preferences-system-symbolic"),
            SettingsPage("advanced", "Advanced", "applications-engineering-symbolic"),
            SettingsPage("about", "About", "help-about-symbolic"),
        ]
        pages_by_name = {page.name: page for page in self._pages}

        # Aliases so the build methods keep targeting familiar boxes.
        self.dictation_page = pages_by_name["dictation"]
        self.shortcuts_tab = self.dictation_page.box
        self.recognition_settings_tab = self.dictation_page.box
        self.speech_engine_tab = pages_by_name["model"].box
        self.audio_tab = pages_by_name["audio"].box
        self.power_tab = pages_by_name["performance"].box
        self.general_tab = pages_by_name["application"].box
        self.advanced_tab = pages_by_name["advanced"].box
        self.about_tab = pages_by_name["about"].box

        # Each page is wrapped in a vertical ScrolledWindow: without one, the
        # stack's minimum height is the tallest page's full content, which
        # overrides set_default_size and can exceed the monitor.
        def _scrollable(tab):
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_shadow_type(Gtk.ShadowType.NONE)
            scroller.add(tab)
            return scroller

        # Content stack + sidebar navigation with settings search
        self.settings_stack = Gtk.Stack()
        self.settings_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.settings_stack.set_transition_duration(120)
        self.settings_stack.set_hexpand(True)
        for page in self._pages:
            self.settings_stack.add_titled(_scrollable(page.box), page.name, page.title)
        self.settings_stack.add_named(self._build_search_empty_page(), "search-empty")
        self.settings_stack.connect("notify::visible-child", self._on_settings_page_changed)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_box.get_style_context().add_class("settings-sidebar")
        sidebar_box.set_size_request(200, -1)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search settings…")
        self.search_entry.get_style_context().add_class("settings-search")
        self.search_entry.connect("search-changed", self._on_search_changed)
        sidebar_box.pack_start(self.search_entry, False, False, 0)

        self.sidebar_listbox = Gtk.ListBox()
        self.sidebar_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for page in self._pages:
            self.sidebar_listbox.add(self._build_sidebar_row(page))
        self.sidebar_listbox.connect("row-selected", self._on_sidebar_row_selected)
        sidebar_box.pack_start(self.sidebar_listbox, True, True, 0)

        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        main_box.pack_start(sidebar_box, False, False, 0)
        main_box.pack_start(self.settings_stack, True, True, 0)
        self.get_content_area().pack_start(main_box, True, True, 0)

        # Search state: baseline visibility snapshot while a query is active.
        self._search_baseline = None
        self._search_previous_page = None

        # Set content_box to speech_engine_tab for backward compatibility
        self.content_box = self.speech_engine_tab

        # Build UI sections into their topic pages
        self._build_shortcuts_section()
        self._build_recognition_section()
        self._build_engine_section()
        self._build_remote_server_section()
        self._build_audio_section()
        self._build_auto_pause_section()
        self._build_model_keepalive_section()
        self._build_gpu_section()
        self._build_general_section()
        self._build_advanced_section()
        self._build_about_section()
        self._build_sidebar_footer(sidebar_box)

        # Record searchable groups vs. loose extras per page
        for page in self._pages:
            page.collect_children()

        # Load settings and populate UI
        self._load_and_apply_settings()

        self.connect("response", self._on_settings_dialog_response)
        self.connect("key-press-event", self._on_dialog_key_press)

        # Show everything first
        self.show_all()
        # Release notes stay hidden until a successful update check.
        self.release_notes_group.hide()
        # Re-hide the About "New" badge if show_all revealed it without a pending update.
        self._set_about_update_badge(self._pending_update is not None)
        # Seed About from a tray background check (opens with notes already filled).
        self._seed_pending_update_ui()
        if self._initial_page:
            self.navigate_to_page(self._initial_page)
        else:
            self.sidebar_listbox.select_row(self.sidebar_listbox.get_row_at_index(0))

        # Then update visibility of engine-specific elements
        self._update_engine_specific_ui()

        # Initialize recognition progress UI
        self.update_recognition_progress("Idle")

        # Connect to recognition manager for progress updates
        self.connect_to_recognition_manager()

        # Initialization complete - enable auto-apply
        self._initializing = False

    # ------------------------------------------------------------------
    # Navigation: sidebar, stack, and settings search
    # ------------------------------------------------------------------

    def navigate_to_page(self, page_name: str) -> bool:
        """Select a settings page by its internal name (e.g. ``about``)."""
        for page in self._pages:
            if page.name == page_name and page.sidebar_row is not None:
                self.sidebar_listbox.select_row(page.sidebar_row)
                return True
        return False

    def _build_sidebar_row(self, page: SettingsPage) -> Gtk.ListBoxRow:
        """Build one sidebar navigation row (icon + title + match badge)."""
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("sidebar-row")
        row.page_name = page.name

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name(page.icon_name, Gtk.IconSize.MENU)
        hbox.pack_start(icon, False, False, 0)

        label = Gtk.Label(label=page.title, xalign=0)
        hbox.pack_start(label, True, True, 0)

        update_badge = Gtk.Label(label="New")
        update_badge.get_style_context().add_class("sidebar-update-badge")
        update_badge.set_no_show_all(True)
        update_badge.hide()
        hbox.pack_end(update_badge, False, False, 0)

        match_label = Gtk.Label(label="")
        match_label.get_style_context().add_class("sidebar-match-count")
        match_label.set_no_show_all(True)
        hbox.pack_end(match_label, False, False, 0)

        row.add(hbox)
        page.sidebar_row = row
        page.match_count_label = match_label
        page.update_badge_label = update_badge
        if page.name == "about" and self._pending_update is not None:
            update_badge.show()
        return row

    def _build_search_empty_page(self) -> Gtk.Widget:
        """Build the stack page shown when a search has no results."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name("edit-find-symbolic", Gtk.IconSize.DIALOG)
        icon.set_opacity(0.4)
        box.pack_start(icon, False, False, 0)

        title = Gtk.Label(label="No matching settings")
        title.get_style_context().add_class("search-empty-title")
        box.pack_start(title, False, False, 0)

        self.search_empty_label = Gtk.Label(label="Try a different search term.")
        self.search_empty_label.get_style_context().add_class("preference-row-subtitle")
        box.pack_start(self.search_empty_label, False, False, 0)
        return box

    def _on_sidebar_row_selected(self, listbox, row):
        """Switch the stack to the page selected in the sidebar."""
        if row is not None:
            self.settings_stack.set_visible_child_name(row.page_name)

    def _on_settings_page_changed(self, stack, pspec):
        """Persist deferred edits when the visible settings page changes."""
        visible = stack.get_visible_child_name()
        if visible != "advanced":
            self._flush_advanced_prompt_if_dirty()
        if visible == "about" and not self._update_auto_checked:
            self._update_auto_checked = True
            self._start_update_check()

    def _open_web_url(self, url: str) -> None:
        """Open a trusted project URL in the user's default browser."""
        if not url or not is_trusted_release_url(url):
            logger.warning("Refusing to open untrusted URL: %s", url)
            return
        try:
            if hasattr(Gtk, "show_uri_on_window"):
                Gtk.show_uri_on_window(self, url, Gdk.CURRENT_TIME)
            else:
                Gtk.show_uri(None, url, Gdk.CURRENT_TIME)
        except Exception as exc:
            logger.warning("Failed to open URL %s: %s", url, exc)

    def _on_dialog_key_press(self, widget, event):
        """Dialog-level shortcuts: Ctrl+F focuses search, Ctrl+W closes, Esc clears search."""
        keyname = (Gdk.keyval_name(event.keyval) or "").lower()
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)

        if ctrl and keyname == "f":
            self.search_entry.grab_focus()
            return True
        if ctrl and keyname == "w":
            self.response(Gtk.ResponseType.CLOSE)
            return True
        if keyname == "escape" and self.search_entry.get_text():
            # First Esc clears the search; a second one closes the dialog
            # through the default Gtk.Dialog binding.
            self.search_entry.set_text("")
            return True
        return False

    def _snapshot_search_baseline(self):
        """Remember pre-search visibility so clearing the query restores it."""
        visible_page = self.settings_stack.get_visible_child_name()
        page_names = {page.name for page in self._pages}
        self._search_previous_page = visible_page if visible_page in page_names else "dictation"

        baseline = {"rows": {}, "groups": {}, "extras": {}}
        for page in self._pages:
            for group in page.groups:
                visible = group.get_visible()
                parent = group.get_parent()
                while visible and parent is not None and parent is not page.box:
                    if isinstance(parent, Gtk.Revealer) and not parent.get_reveal_child():
                        visible = False
                    else:
                        visible = parent.get_visible()
                    parent = parent.get_parent()
                baseline["groups"][group] = visible
                for row in group.rows:
                    baseline["rows"][row] = row.get_visible()
            for extra in page.extras:
                baseline["extras"][extra] = extra.get_visible()
        self._search_baseline = baseline

    def _restore_search_baseline(self):
        """Restore visibility recorded before the search started."""
        if self._search_baseline is None:
            return
        for widgets in self._search_baseline.values():
            for widget, visible in widgets.items():
                widget.set_visible(visible)
        self._search_baseline = None

        for page in self._pages:
            page.match_count_label.hide()
            page.sidebar_row.set_sensitive(True)
            page.sidebar_row.show()

        # Badge visibility follows _pending_update (cleared on failed About checks
        # so a stale New badge cannot reappear when search is cleared).
        self._set_about_update_badge(self._pending_update is not None)

        # Engine-driven visibility is authoritative; re-apply it in case a
        # control changed while the filter was active.
        self._update_engine_specific_ui()

        page = next(
            (page for page in self._pages if page.name == self._search_previous_page),
            self._pages[0],
        )
        self.sidebar_listbox.select_row(page.sidebar_row)
        self.settings_stack.set_visible_child_name(page.name)
        self._search_previous_page = None

    def _on_search_changed(self, entry):
        """Live-filter settings rows across all pages."""
        query = entry.get_text().strip()

        if not query:
            self._restore_search_baseline()
            return

        if self._search_baseline is None:
            self._snapshot_search_baseline()

        baseline = self._search_baseline
        first_match_page = None
        for page in self._pages:
            page_matches = 0
            for group in page.groups:
                if not baseline["groups"].get(group, True):
                    # Whole group hidden by engine-specific logic; skip it.
                    group.hide()
                    continue
                group_title_match = _row_matches_query(
                    query, group.title, group.description, group.keywords
                )
                visible_rows = 0
                for row in group.rows:
                    if not baseline["rows"].get(row, True):
                        row.hide()
                        continue
                    row_matches = group_title_match or (
                        isinstance(row, PreferenceRow) and row.matches_query(query)
                    )
                    row.set_visible(row_matches)
                    if row_matches:
                        visible_rows += 1
                group.set_visible(visible_rows > 0)
                page_matches += visible_rows
            for extra in page.extras:
                extra.hide()

            if page_matches > 0:
                if page.update_badge_label is not None:
                    page.update_badge_label.hide()
                page.match_count_label.set_text(str(page_matches))
                page.match_count_label.show()
                page.sidebar_row.set_sensitive(True)
                if first_match_page is None:
                    first_match_page = page
            else:
                if page.update_badge_label is not None:
                    page.update_badge_label.hide()
                page.match_count_label.hide()
                page.sidebar_row.set_sensitive(False)

        if first_match_page is not None:
            self.sidebar_listbox.select_row(first_match_page.sidebar_row)
            self.settings_stack.set_visible_child_name(first_match_page.name)
        else:
            self.sidebar_listbox.unselect_all()
            self.search_empty_label.set_text(f"No settings match \u201c{query}\u201d.")
            self.settings_stack.set_visible_child_name("search-empty")

    def _build_audio_section(self):
        """Build the Audio Input section."""
        group = PreferencesGroup(title="Audio Input")

        # Device selection row
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.audio_device_combo = Gtk.ComboBoxText()
        self.audio_device_combo.set_tooltip_text(
            "Select the microphone to use for voice recognition"
        )
        self.audio_device_combo.set_size_request(_CONTROL_WIDTH, -1)
        _prevent_scroll_on_hover(self.audio_device_combo)
        device_box.pack_start(self.audio_device_combo, True, True, 0)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text("Refresh device list")
        refresh_btn.get_style_context().add_class("flat-button")
        refresh_btn.connect("clicked", self._on_refresh_audio_devices)
        device_box.pack_start(refresh_btn, False, False, 0)

        device_row = PreferenceRow(
            title="Input Device",
            subtitle="Select the microphone for voice recognition",
            widget=device_box,
            keywords=("microphone", "mic", "input"),
        )
        group.add_row(device_row)

        # Microphone test row; the live level shows in the status strip below.
        self.test_audio_btn = Gtk.Button(label="Test")
        self.test_audio_btn.set_tooltip_text("Record 2 seconds and check the level")
        self.test_audio_btn.connect("clicked", self._on_test_audio_clicked)

        level_row = PreferenceRow(
            title="Microphone Test",
            subtitle="Record 2 seconds; the level meter below shows the result",
            widget=self.test_audio_btn,
            keywords=("audio level", "check", "volume"),
        )
        group.add_row(level_row)

        self.audio_tab.pack_start(group, False, False, 0)

        # Sound Effects section
        sound_group = PreferencesGroup(
            title="Sound Effects",
            description=(
                "The switch mutes every cue, including errors. Off only skips start and stop."
            ),
        )
        self.sound_effects_switch = Gtk.Switch()
        self.sound_effects_switch.set_tooltip_text(
            "Play sounds when recording starts, stops, or encounters errors"
        )
        sound_row = PreferenceRow(
            title="Enable Sound Effects",
            subtitle="Play audio feedback for recording events",
            widget=self.sound_effects_switch,
            keywords=("tone", "chime", "cue", "feedback"),
        )
        sound_group.add_row(sound_row)

        self.sound_tone_combo = Gtk.ComboBoxText()
        self.sound_tone_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.sound_tone_combo.set_tooltip_text("Start and stop sound used while dictating")
        _prevent_scroll_on_hover(self.sound_tone_combo)
        for tone_id, label in SOUND_EFFECT_TONES:
            self.sound_tone_combo.append(tone_id, label)
        tone_row = PreferenceRow(
            title="Dictation Tone",
            subtitle="Start and stop cues. Off is silent for those two.",
            widget=self.sound_tone_combo,
            keywords=("tone", "chime", "voca", "lift", "preview"),
        )
        sound_group.add_row(tone_row)

        self.preview_tone_btn = Gtk.Button(label="Preview")
        self.preview_tone_btn.set_tooltip_text("Play the start cue, then the stop cue")
        self.preview_tone_row = PreferenceRow(
            title="Preview Tone",
            subtitle="Play the start cue, then the stop cue",
            widget=self.preview_tone_btn,
            keywords=("tone", "preview", "listen"),
        )
        sound_group.add_row(self.preview_tone_row)

        self.audio_tab.pack_start(sound_group, False, False, 0)
        self.sound_effects_switch.connect("state-set", self._on_sound_effects_toggled)
        self.sound_tone_combo.connect("changed", self._on_sound_tone_changed)
        self.preview_tone_btn.connect("clicked", self._on_preview_tone_clicked)

        # Populate devices
        self._populate_audio_devices()
        self.audio_device_combo.connect("changed", self._on_audio_device_changed)

    def _build_general_section(self):
        """Build the Application page: general behavior."""
        group = PreferencesGroup(title="General")

        self.autostart_switch = Gtk.Switch()
        autostart_row = PreferenceRow(
            title="Start on Login",
            subtitle="Automatically start Vocalinux when you log in",
            widget=self.autostart_switch,
            keywords=("autostart", "boot", "startup"),
        )
        group.add_row(autostart_row)

        self.start_minimized_switch = Gtk.Switch()
        start_minimized_row = PreferenceRow(
            title="Start Minimized",
            subtitle="Start minimized to system tray instead of showing window",
            widget=self.start_minimized_switch,
            keywords=("tray",),
        )
        group.add_row(start_minimized_row)

        self.missing_tray_warning_switch = Gtk.Switch()
        missing_tray_warning_row = PreferenceRow(
            title="Warn if tray support is not detected",
            subtitle="Show a warning when Vocalinux cannot detect AppIndicator support",
            widget=self.missing_tray_warning_switch,
            keywords=("tray", "appindicator", "warning"),
        )
        group.add_row(missing_tray_warning_row)

        self.general_tab.pack_start(group, False, False, 0)

        self.autostart_switch.connect("state-set", self._on_autostart_toggled)
        self.start_minimized_switch.connect("state-set", self._on_start_minimized_toggled)
        self.missing_tray_warning_switch.connect("state-set", self._on_missing_tray_warning_toggled)

    def _build_auto_pause_section(self):
        """Build Auto-Pause settings: enable toggle + process name list."""
        group = PreferencesGroup(
            title="Auto-Pause for Games & Apps",
            description=(
                "While any app in the list is running, Vocalinux pauses dictation and "
                "unloads the speech model to free CPU, GPU, and memory. Everything "
                "resumes automatically when the app closes."
            ),
            keywords=("process", "program", "game"),
        )

        self.auto_pause_switch = Gtk.Switch()
        self.auto_pause_switch.set_tooltip_text(
            "Pause dictation and unload the speech model while any listed app is running"
        )
        enable_row = PreferenceRow(
            title="Pause for Listed Apps",
            subtitle="Free resources while any app below is running",
            widget=self.auto_pause_switch,
        )
        group.add_row(enable_row)

        # Add process name: entry + Add button
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_box.set_margin_top(8)
        add_box.set_margin_bottom(4)
        add_box.set_margin_start(16)
        add_box.set_margin_end(16)

        self.auto_pause_entry = Gtk.Entry()
        self.auto_pause_entry.set_placeholder_text("Process name (e.g. overwatch, steam)")
        self.auto_pause_entry.set_hexpand(True)
        self.auto_pause_entry.set_tooltip_text(
            "Process name, matched case-insensitively. "
            "For Windows games under Wine/Proton, the .exe suffix is optional."
        )
        add_box.pack_start(self.auto_pause_entry, True, True, 0)

        self.auto_pause_add_btn = Gtk.Button(label="Add")
        self.auto_pause_add_btn.set_tooltip_text("Add this process name to the list")
        self.auto_pause_add_btn.connect("clicked", self._on_auto_pause_add_clicked)
        self.auto_pause_entry.connect("activate", self._on_auto_pause_add_clicked)
        add_box.pack_start(self.auto_pause_add_btn, False, False, 0)

        self.auto_pause_pick_btn = Gtk.Button(label="Choose Running App…")
        self.auto_pause_pick_btn.set_tooltip_text("Pick from apps that are running right now")
        self.auto_pause_pick_btn.connect("clicked", self._on_auto_pause_pick_running)
        add_box.pack_start(self.auto_pause_pick_btn, False, False, 0)

        # Custom row for the add controls (not a PreferenceRow)
        add_row = Gtk.ListBoxRow()
        add_row.set_activatable(False)
        add_row.add(add_box)
        group.add_row(add_row)

        # List of configured apps; the empty-state text is an in-list
        # placeholder so there is no blank hole when the list is empty.
        self.auto_pause_listbox = Gtk.ListBox()
        self.auto_pause_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.auto_pause_listbox.set_activate_on_single_click(False)

        self.auto_pause_empty_label = Gtk.Label(
            label="No apps in the list yet. Type a process name or choose a running app above.",
            xalign=0.5,
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        self.auto_pause_empty_label.get_style_context().add_class("preference-row-subtitle")
        self.auto_pause_empty_label.set_margin_top(12)
        self.auto_pause_empty_label.set_margin_bottom(12)
        self.auto_pause_empty_label.set_margin_start(16)
        self.auto_pause_empty_label.set_margin_end(16)
        self.auto_pause_empty_label.show()
        self.auto_pause_listbox.set_placeholder(self.auto_pause_empty_label)

        list_scrolled = Gtk.ScrolledWindow()
        list_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scrolled.set_min_content_height(48)
        list_scrolled.set_max_content_height(160)
        list_scrolled.set_margin_start(8)
        list_scrolled.set_margin_end(8)
        list_scrolled.set_margin_bottom(8)
        list_scrolled.add(self.auto_pause_listbox)

        list_row = Gtk.ListBoxRow()
        list_row.set_activatable(False)
        list_row.add(list_scrolled)
        group.add_row(list_row)

        self.power_tab.pack_start(group, False, False, 0)

        self.auto_pause_switch.connect("state-set", self._on_auto_pause_enabled_toggled)

    def _update_auto_pause_sensitivity(self, enabled: bool) -> None:
        """Gray out the app-list controls while auto-pause is disabled."""
        for widget in (
            self.auto_pause_entry,
            self.auto_pause_add_btn,
            self.auto_pause_pick_btn,
            self.auto_pause_listbox,
        ):
            widget.set_sensitive(enabled)

    def _get_auto_pause_apps(self) -> list:
        """Return a clean list of configured auto-pause process names."""
        apps = self.config_manager.get("auto_pause", "apps", []) or []
        if not isinstance(apps, list):
            return []
        return [str(a).strip() for a in apps if a and str(a).strip()]

    def _save_auto_pause_apps(self, apps: list) -> None:
        # Deduplicate case-insensitively while preserving first-seen casing
        seen = set()
        cleaned = []
        for name in apps:
            key = name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(name.strip())
        self.config_manager.set("auto_pause", "apps", cleaned)
        self.config_manager.save_settings()
        self._refresh_auto_pause_list()

    def _refresh_auto_pause_list(self) -> None:
        """Rebuild the auto-pause app list UI from config."""
        if not hasattr(self, "auto_pause_listbox"):
            return

        for child in list(self.auto_pause_listbox.get_children()):
            self.auto_pause_listbox.remove(child)

        apps = self._get_auto_pause_apps()
        for name in apps:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hbox.set_margin_top(6)
            hbox.set_margin_bottom(6)
            hbox.set_margin_start(16)
            hbox.set_margin_end(16)

            label = Gtk.Label(label=name, xalign=0)
            label.set_hexpand(True)
            hbox.pack_start(label, True, True, 0)

            remove_btn = Gtk.Button(label="Remove")
            remove_btn.set_tooltip_text(f"Remove {name} from auto-pause list")
            remove_btn.connect("clicked", self._on_auto_pause_remove_clicked, name)
            hbox.pack_start(remove_btn, False, False, 0)

            row.add(hbox)
            self.auto_pause_listbox.add(row)

        self.auto_pause_listbox.show_all()

    def _on_auto_pause_enabled_toggled(self, widget, state):
        enabled = bool(state)
        self._update_auto_pause_sensitivity(enabled)
        if self._initializing or self._applying_settings:
            return False
        logger.info("Auto-pause enabled toggled: %s", enabled)
        self.config_manager.set("auto_pause", "enabled", enabled)
        self.config_manager.save_settings()
        return False

    def _on_auto_pause_add_clicked(self, widget):
        if self._initializing or self._applying_settings:
            return
        name = self.auto_pause_entry.get_text().strip()
        if not name:
            return
        # Strip path if user pasted a full path
        name = os.path.basename(name)
        if name.lower().endswith(".exe"):
            name = name[:-4]
        apps = self._get_auto_pause_apps()
        if name.lower() in {a.lower() for a in apps}:
            self.auto_pause_entry.set_text("")
            return
        apps.append(name)
        self._save_auto_pause_apps(apps)
        self.auto_pause_entry.set_text("")
        logger.info("Added auto-pause app: %s", name)

    def _on_auto_pause_remove_clicked(self, widget, name: str):
        if self._initializing or self._applying_settings:
            return
        apps = [a for a in self._get_auto_pause_apps() if a.lower() != name.lower()]
        self._save_auto_pause_apps(apps)
        logger.info("Removed auto-pause app: %s", name)

    def _on_auto_pause_pick_running(self, widget):
        """Show a simple dialog listing running process names to add."""
        if self._initializing or self._applying_settings:
            return

        try:
            import psutil
        except ImportError:
            logger.warning("psutil not available for process picker")
            return

        names: set[str] = set()
        for proc in psutil.process_iter(["name"]):
            try:
                n = proc.info.get("name")
                if n:
                    base = os.path.basename(n)
                    if base.lower().endswith(".exe"):
                        base = base[:-4]
                    names.add(base)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not names:
            return

        dialog = Gtk.Dialog(title="Choose a Running App", transient_for=self, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Add", Gtk.ResponseType.OK)
        dialog.set_default_size(360, 400)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_margin_top(8)
        scrolled.set_margin_bottom(8)
        scrolled.set_margin_start(8)
        scrolled.set_margin_end(8)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        already = {a.lower() for a in self._get_auto_pause_apps()}
        for name in sorted(names, key=str.lower):
            if name.lower() in already:
                continue
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=name, xalign=0)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            row.add(label)
            listbox.add(row)
        scrolled.add(listbox)
        dialog.get_content_area().pack_start(scrolled, True, True, 0)
        dialog.show_all()

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            selected = listbox.get_selected_rows()
            apps = self._get_auto_pause_apps()
            existing = {a.lower() for a in apps}
            for row in selected:
                label = row.get_child()
                if isinstance(label, Gtk.Label):
                    name = label.get_text().strip()
                    if name and name.lower() not in existing:
                        apps.append(name)
                        existing.add(name.lower())
            self._save_auto_pause_apps(apps)
        dialog.destroy()

    def _build_model_keepalive_section(self):
        """Build idle unload settings: enable toggle + idle timeout."""
        group = PreferencesGroup(
            title="Unload When Idle",
            description=(
                "After a period of inactivity, unload the speech model to save memory "
                "and battery — on hybrid-GPU laptops (NVIDIA Optimus) this lets the "
                "GPU sleep. The next dictation reloads the model automatically, which "
                "may take a moment on larger models."
            ),
        )

        self.model_keepalive_switch = Gtk.Switch()
        self.model_keepalive_switch.set_tooltip_text(
            "Unload the speech model after the idle timeout to save memory and battery"
        )
        enable_row = PreferenceRow(
            title="Unload Model When Idle",
            subtitle="Free memory and GPU power after a period of inactivity",
            widget=self.model_keepalive_switch,
        )
        group.add_row(enable_row)

        self.model_keepalive_timeout_combo = Gtk.ComboBoxText()
        self.model_keepalive_timeout_combo.set_size_request(_CONTROL_WIDTH, -1)
        # id = seconds as string
        for seconds, label in (
            (60, "1 minute"),
            (300, "5 minutes"),
            (600, "10 minutes"),
            (900, "15 minutes"),
            (1800, "30 minutes"),
        ):
            self.model_keepalive_timeout_combo.append(str(seconds), label)
        self.model_keepalive_timeout_combo.set_tooltip_text(
            "How long to wait after the last dictation before unloading the model"
        )
        _prevent_scroll_on_hover(self.model_keepalive_timeout_combo)
        timeout_row = PreferenceRow(
            title="Idle Timeout",
            subtitle="Unload the model after this much inactivity",
            widget=self.model_keepalive_timeout_combo,
        )
        group.add_row(timeout_row)

        self.power_tab.pack_start(group, False, False, 0)

        self.model_keepalive_switch.connect("state-set", self._on_model_keepalive_enabled_toggled)
        self.model_keepalive_timeout_combo.connect(
            "changed", self._on_model_keepalive_timeout_changed
        )

    def _update_model_keepalive_sensitivity(self, enabled: bool) -> None:
        """Gray out the idle timeout selector while idle unload is disabled."""
        self.model_keepalive_timeout_combo.set_sensitive(enabled)

    def _on_model_keepalive_enabled_toggled(self, widget, state):
        enabled = bool(state)
        self._update_model_keepalive_sensitivity(enabled)
        if self._initializing or self._applying_settings:
            return False
        logger.info("Model keep-alive enabled toggled: %s", enabled)
        self.config_manager.set("model_keepalive", "enabled", enabled)
        self.config_manager.save_settings()
        return False

    def _on_model_keepalive_timeout_changed(self, widget):
        if self._initializing or self._applying_settings:
            return
        active_id = self.model_keepalive_timeout_combo.get_active_id()
        if not active_id:
            return
        try:
            seconds = int(active_id)
        except (TypeError, ValueError):
            return
        logger.info("Model keep-alive timeout set to %s seconds", seconds)
        self.config_manager.set("model_keepalive", "idle_timeout_seconds", seconds)
        self.config_manager.save_settings()

    def _on_autostart_toggled(self, widget, state):
        """Handle toggle of the autostart switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Autostart toggled: {enabled}")

        from . import autostart_manager

        if autostart_manager.set_autostart(enabled):
            self.config_manager.set("general", "autostart", enabled)
            self.config_manager.save_settings()
            logger.info(f"Autostart {'enabled' if enabled else 'disabled'}")
            return False

        return True

    def _on_start_minimized_toggled(self, widget, state):
        """Handle toggle of the start minimized switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Start minimized toggled: {enabled}")
        self.config_manager.set("ui", "start_minimized", enabled)
        self.config_manager.save_settings()
        logger.info(f"Start minimized {'enabled' if enabled else 'disabled'}")
        return False

    def _on_missing_tray_warning_toggled(self, widget, state):
        """Handle toggle of the missing tray support warning switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Missing tray warning toggled: {enabled}")
        self.config_manager.set("ui", "show_missing_tray_warning", enabled)
        self.config_manager.save_settings()
        return False

    def _on_copy_to_clipboard_toggled(self, widget, state):
        """Handle toggle of the copy to clipboard switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Copy to clipboard toggled: {enabled}")
        self.config_manager.set("text_injection", "copy_to_clipboard", enabled)
        self.config_manager.save_settings()
        logger.info(f"Copy to clipboard {'enabled' if enabled else 'disabled'}")
        return False

    def _on_auto_capitalize_toggled(self, widget, state):
        """Handle toggle of the auto-capitalize switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Auto-capitalize toggled: {enabled}")
        self.config_manager.set("text_injection", "auto_capitalize", enabled)
        self.config_manager.save_settings()
        logger.info(f"Auto-capitalize {'enabled' if enabled else 'disabled'}")
        return False

    def _on_append_trailing_space_toggled(self, widget, state):
        """Handle toggle of the trailing space after dictation switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Append trailing space toggled: {enabled}")
        self.config_manager.set("text_injection", "append_trailing_space", enabled)
        self.config_manager.save_settings()
        logger.info(f"Append trailing space {'enabled' if enabled else 'disabled'}")
        return False

    def _on_sound_effects_toggled(self, widget, state):
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Sound effects toggled: {enabled}")
        self.config_manager.set_sound_effects_enabled(enabled)
        self.config_manager.save_settings()
        logger.info(f"Sound effects {'enabled' if enabled else 'disabled'}")
        return False

    def _update_tone_preview_subtitle(self, tone_id: str) -> None:
        if tone_id == "off":
            self.preview_tone_row.set_subtitle("Off has no start or stop cue")
            self.preview_tone_btn.set_tooltip_text("Off has no start or stop cue")
        else:
            self.preview_tone_row.set_subtitle("Play the start cue, then the stop cue")
            self.preview_tone_btn.set_tooltip_text("Play the start cue, then the stop cue")

    def _on_sound_tone_changed(self, combo):
        tone_id = combo.get_active_id() or DEFAULT_SOUND_EFFECT_TONE
        self._update_tone_preview_subtitle(tone_id)
        if self._initializing or self._applying_settings:
            return
        logger.info("Dictation tone selected: %s", tone_id)
        self.config_manager.set_sound_effects_tone(tone_id)
        self.config_manager.save_settings()

    def _on_preview_tone_clicked(self, _widget):
        from .audio_feedback import preview_tone

        tone_id = self.sound_tone_combo.get_active_id() or DEFAULT_SOUND_EFFECT_TONE
        self._update_tone_preview_subtitle(tone_id)
        preview_tone(tone_id)

    def _build_engine_section(self):
        """Build the Speech Engine section."""
        group = PreferencesGroup(title="Speech Engine")

        # Engine selection
        self.engine_combo = Gtk.ComboBoxText()
        self.engine_combo.set_size_request(_CONTROL_WIDTH, -1)
        _prevent_scroll_on_hover(self.engine_combo)
        engine_row = PreferenceRow(
            title="Engine",
            subtitle="Speech recognition backend",
            widget=self.engine_combo,
        )
        group.add_row(engine_row)

        # Model size selection
        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.model_combo.set_tooltip_text(MODEL_SIZE_TOOLTIP)
        _prevent_scroll_on_hover(self.model_combo)
        self.model_row = PreferenceRow(
            title="Model Size",
            subtitle="Larger models are more accurate but slower",
            widget=self.model_combo,
        )
        self.model_row.set_tooltip_text(MODEL_SIZE_TOOLTIP)
        group.add_row(self.model_row)

        # whisper.cpp specialization selection
        self.model_variant_combo = Gtk.ComboBoxText()
        self.model_variant_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.model_variant_combo.set_tooltip_text(MODEL_SPECIALIZATION_TOOLTIP)
        _prevent_scroll_on_hover(self.model_variant_combo)
        self.model_variant_row = PreferenceRow(
            title="Specialization",
            subtitle="Variant for language, speed, or memory use",
            widget=self.model_variant_combo,
        )
        self.model_variant_row.set_tooltip_text(MODEL_SPECIALIZATION_TOOLTIP)
        group.add_row(self.model_variant_row)

        # Language selection (searchable: type to filter the 30+ language list)
        self.language_combo = Gtk.ComboBoxText.new_with_entry()
        self.language_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.language_combo.set_tooltip_text(LANGUAGE_TOOLTIP)
        _prevent_scroll_on_hover(self.language_combo)
        _attach_language_combo_search(self.language_combo)
        language_entry = self.language_combo.get_child()
        if language_entry is not None:
            language_entry.connect("activate", self._on_language_entry_activate)
            language_entry.connect("focus-out-event", self._on_language_entry_focus_out)
        self.language_row = PreferenceRow(
            title="Language",
            subtitle="Type to search, or pick from the list",
            widget=self.language_combo,
        )
        self.language_row.set_tooltip_text(LANGUAGE_TOOLTIP)
        group.add_row(self.language_row)

        self.content_box.pack_start(group, False, False, 0)

        # Model info card (shown below the group)
        self.model_info_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.model_info_card.get_style_context().add_class("model-info-card")
        self.model_info_card.set_margin_start(4)
        self.model_info_card.set_margin_end(4)

        self.model_info_title = Gtk.Label(xalign=0)
        self.model_info_title.get_style_context().add_class("model-info-title")
        self.model_info_card.pack_start(self.model_info_title, False, False, 0)

        self.model_info_subtitle = Gtk.Label(xalign=0, wrap=True)
        self.model_info_subtitle.get_style_context().add_class("model-info-subtitle")
        self.model_info_card.pack_start(self.model_info_subtitle, False, False, 0)

        self.model_recommendation = Gtk.Label(xalign=0, wrap=True)
        self.model_recommendation.get_style_context().add_class("tip-label")
        self.model_info_card.pack_start(self.model_recommendation, False, False, 0)

        # Language warning (e.g. auto-detect, English-only models) lives in
        # the card so there is a single explanation surface below the group.
        self.language_warning = Gtk.Label(label="", use_markup=True, xalign=0, wrap=True)
        self.language_warning.get_style_context().add_class("status-warning")
        self.language_warning.set_no_show_all(True)
        self.model_info_card.pack_start(self.language_warning, False, False, 0)

        # Symbol legend as a muted caption inside the card
        legend = Gtk.Label(
            label="✓ Downloaded    ↓ Will download    ★ Recommended",
            xalign=0,
        )
        legend.get_style_context().add_class("tip-label")
        self.model_info_card.pack_start(legend, False, False, 0)

        self.content_box.pack_start(self.model_info_card, False, False, 0)

        self.unused_models_group = PreferencesGroup(
            keywords=("delete", "remove", "unused", "disk", "storage", "downloaded"),
        )
        self.unused_models_group.title = "Unused downloads"
        self.unused_models_group.description = "On disk, but not the model currently selected"

        self.unused_expander = Gtk.Expander(label="Unused downloads")
        self.unused_expander.set_expanded(False)
        self.unused_expander.set_use_underline(False)
        self.unused_expander.set_tooltip_text(
            "Leftover model files on disk. Expand to delete them one at a time."
        )
        self.unused_expander.get_style_context().add_class("unused-downloads-expander")

        self.unused_models_scroll = Gtk.ScrolledWindow()
        self.unused_models_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.unused_models_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.unused_models_scroll.set_propagate_natural_height(True)
        self.unused_models_scroll.set_max_content_height(_UNUSED_DOWNLOADS_MAX_HEIGHT)
        # Keep the scrollbar in the layout: an overlay one stays invisible until
        # hovered, so a list clipped by the cap looks like it has no more rows.
        self.unused_models_scroll.set_overlay_scrolling(False)

        # ListBox is GtkScrollable, so wrapping it in a Box forces a Viewport
        # and lets the expander child report a real height.
        list_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.unused_models_group.remove(self.unused_models_group.listbox)
        list_holder.pack_start(self.unused_models_group.listbox, False, False, 0)
        self.unused_models_scroll.add(list_holder)
        self.unused_expander.add(self.unused_models_scroll)
        self.unused_models_group.pack_start(self.unused_expander, False, False, 0)
        self.content_box.pack_start(self.unused_models_group, False, False, 0)

        # Connect signals
        self.engine_combo.connect("changed", self._on_engine_changed)
        self.model_combo.connect("changed", self._on_model_changed)
        self.model_variant_combo.connect("changed", self._on_model_variant_changed)
        self.language_combo.connect("changed", self._on_language_changed)

    def _on_remote_api_settings_changed(self, widget):
        """Handle remote API URL/Key/endpoint changes."""
        if self._initializing or self._applying_settings:
            return

        url = self.remote_api_url_entry.get_text().strip()
        key = self.remote_api_key_entry.get_text().strip()
        endpoint = self.remote_api_endpoint_combo.get_active_id() or "/inference"
        model = self.remote_api_model_entry.get_text().strip() or "whisper-1"

        self.config_manager.set("speech_recognition", "remote_api_url", url)
        self.config_manager.set("speech_recognition", "remote_api_key", key)
        self.config_manager.set("speech_recognition", "remote_api_endpoint", endpoint)
        self.config_manager.set("speech_recognition", "remote_api_model", model)
        self.config_manager.save_settings()

        # Auto apply only if remote engine is currently active
        engine_text = self.engine_combo.get_active_text()
        engine = _engine_from_display(engine_text) if engine_text else "vosk"
        if engine == "remote_api":
            self._auto_apply_settings()

    def _on_test_remote_connection(self, widget):
        """Test remote server connection."""
        url = self.remote_api_url_entry.get_text().strip()
        if not url:
            self.remote_status_label.set_markup(
                "<span foreground='#c01c28'>✗ Please enter a server URL</span>"
            )
            return

        self.remote_test_btn.set_sensitive(False)
        self.remote_test_btn.set_label("Testing...")
        self.remote_status_label.set_markup("<i>Connecting...</i>")

        key = self.remote_api_key_entry.get_text().strip()
        endpoint = self.remote_api_endpoint_combo.get_active_id() or "/inference"

        def test_connection(url=url, key=key, endpoint=endpoint):
            try:
                import requests

                headers = {}
                if key:
                    headers["Authorization"] = f"Bearer {key}"

                clean_url = url.rstrip("/")

                session = requests.Session()
                try:
                    response = session.get(clean_url, headers=headers, timeout=5)

                    server_info = ""

                    try:
                        if endpoint == "/v1/audio/transcriptions":
                            openai_resp = session.get(
                                f"{clean_url}/v1/models", headers=headers, timeout=5
                            )
                            if openai_resp.status_code == 200:
                                server_info = " (OpenAI compatible)"
                        elif endpoint == "/inference":
                            whispercpp_resp = session.get(
                                f"{clean_url}/inference", headers=headers, timeout=5
                            )
                            if whispercpp_resp.status_code != 404:
                                server_info = " (whisper.cpp server)"
                    except Exception:
                        pass

                    GLib.idle_add(
                        self.remote_status_label.set_markup,
                        f"<span foreground='#26a269'>✓ Connected! "
                        f"(status={response.status_code}){server_info}</span>",
                    )
                finally:
                    session.close()

            except Exception as e:
                error_msg = str(e)[:80]
                GLib.idle_add(
                    self.remote_status_label.set_markup,
                    f"<span foreground='#c01c28'>✗ Connection failed: {error_msg}</span>",
                )

            GLib.idle_add(self.remote_test_btn.set_sensitive, True)
            GLib.idle_add(self.remote_test_btn.set_label, "Test Connection")

        threading.Thread(target=test_connection, daemon=True).start()

    def _build_recognition_section(self):
        """Build the Listening and Output groups on the Dictation page."""
        group = PreferencesGroup(title="Listening")

        # VAD Sensitivity
        self.vad_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.vad_spin.set_tooltip_text("Higher = more sensitive to quiet speech")
        _prevent_scroll_on_hover(self.vad_spin)
        silero_active = is_silero_available()
        vad_subtitle = (
            "Sensitivity to quiet speech (1-5) — Silero neural VAD"
            if silero_active
            else "Sensitivity to quiet speech (1-5) — amplitude backend"
        )
        self.vad_row = PreferenceRow(
            title="Microphone Sensitivity",
            subtitle=vad_subtitle,
            widget=self.vad_spin,
            keywords=("vad", "voice activity detection"),
        )
        group.add_row(self.vad_row)

        # Silence Timeout
        self.silence_spin = Gtk.SpinButton.new_with_range(0.5, 5.0, 0.1)
        self.silence_spin.set_digits(1)
        self.silence_spin.set_tooltip_text("Wait time after silence before processing speech")
        _prevent_scroll_on_hover(self.silence_spin)
        silence_row = PreferenceRow(
            title="Stop After Silence",
            subtitle="Seconds of silence before processing what you said",
            widget=self.silence_spin,
            keywords=("timeout", "pause"),
        )
        group.add_row(silence_row)

        self.recognition_settings_tab.pack_start(group, False, False, 0)

        # Output group: what happens with the recognized text
        output_group = PreferencesGroup(title="Output")

        self.voice_commands_switch = Gtk.Switch()
        self.voice_commands_switch.set_tooltip_text(
            "Enable voice commands like 'new line', 'period', 'undo', etc.\n"
            "Useful for VOSK engine. Whisper engines handle punctuation automatically."
        )
        voice_commands_row = PreferenceRow(
            title="Voice Commands",
            subtitle="Say 'new line', 'period', 'undo' while dictating",
            widget=self.voice_commands_switch,
            keywords=("punctuation", "editing"),
        )
        output_group.add_row(voice_commands_row)

        self.auto_capitalize_switch = Gtk.Switch()
        self.auto_capitalize_switch.set_tooltip_text(
            "Automatically capitalize the first letter of each sentence. "
            "Works after sentence-ending punctuation (period, exclamation, question mark). "
            "Only applies to Vosk engine - Whisper models output proper capitalization automatically."
        )
        auto_capitalize_row = PreferenceRow(
            title="Auto-Capitalize Sentences",
            subtitle="Capitalize first letter after punctuation (Vosk only)",
            widget=self.auto_capitalize_switch,
            keywords=("capitalization", "casing", "sentence"),
        )
        output_group.add_row(auto_capitalize_row)

        self.copy_to_clipboard_switch = Gtk.Switch()
        self.copy_to_clipboard_switch.set_tooltip_text(
            "Copy recognized text to clipboard after each transcription. "
            "Useful if injection fails or you want to paste elsewhere."
        )
        copy_to_clipboard_row = PreferenceRow(
            title="Copy to Clipboard",
            subtitle="Always copy recognized text to clipboard for easy pasting",
            widget=self.copy_to_clipboard_switch,
            keywords=("paste",),
        )
        output_group.add_row(copy_to_clipboard_row)

        self.append_trailing_space_switch = Gtk.Switch()
        self.append_trailing_space_switch.set_tooltip_text(
            "Append a space after each completed transcription so the next "
            "dictation session continues without gluing onto the previous text "
            '(e.g. "Hello. This" instead of "Hello.This").'
        )
        append_trailing_space_row = PreferenceRow(
            title="Trailing Space After Dictation",
            subtitle="Insert a space after each completed transcription segment",
            widget=self.append_trailing_space_switch,
            keywords=("space", "spacing", "punctuation", "push-to-talk"),
        )
        output_group.add_row(append_trailing_space_row)

        self.recognition_settings_tab.pack_start(output_group, False, False, 0)
        self.copy_to_clipboard_switch.connect("state-set", self._on_copy_to_clipboard_toggled)
        self.auto_capitalize_switch.connect("state-set", self._on_auto_capitalize_toggled)
        self.append_trailing_space_switch.connect(
            "state-set", self._on_append_trailing_space_toggled
        )

        if not silero_active:
            vad_info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            vad_info_box.get_style_context().add_class("info-box")
            vad_info_box.set_margin_start(4)
            vad_info_box.set_margin_end(4)
            vad_info_box.set_margin_top(4)

            info_icon = Gtk.Image.new_from_icon_name(
                "dialog-information-symbolic", Gtk.IconSize.MENU
            )
            vad_info_box.pack_start(info_icon, False, False, 0)

            vad_info_label = Gtk.Label(
                label=(
                    "Neural VAD is more accurate at separating speech from background "
                    "noise. To enable it, install onnxruntime and restart Vocalinux:\n"
                    '    pip install "vocalinux[vad]"'
                ),
                xalign=0,
                wrap=True,
                selectable=True,
            )
            vad_info_label.get_style_context().add_class("tip-label")
            vad_info_box.pack_start(vad_info_label, True, True, 0)

            self.recognition_settings_tab.pack_start(vad_info_box, False, False, 0)

        # Connect signals
        self.vad_spin.connect("value-changed", self._on_vad_changed)
        self.silence_spin.connect("value-changed", self._on_silence_changed)
        self.voice_commands_switch.connect("state-set", self._on_voice_commands_toggled)
        self.auto_capitalize_switch.connect("state-set", self._on_auto_capitalize_toggled)

    def _build_shortcuts_section(self):
        """Build the Keyboard Shortcuts section."""
        group = PreferencesGroup(
            title="Keyboard Shortcuts",
            description="Configure the shortcut to control voice recognition",
        )

        # Mode selection (Toggle vs Push-to-Talk)
        self.shortcut_mode_combo = Gtk.ComboBoxText()
        self.shortcut_mode_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.shortcut_mode_combo.set_tooltip_text(
            "Choose between toggle (double-tap) or push-to-talk mode"
        )
        _prevent_scroll_on_hover(self.shortcut_mode_combo)

        # Populate mode options
        for mode_id, display_name in SHORTCUT_MODES.items():
            self.shortcut_mode_combo.append(mode_id, display_name)

        # Load current mode from config
        current_mode = self.config_manager.get_str("shortcuts", "mode", DEFAULT_SHORTCUT_MODE)
        if not self.shortcut_mode_combo.set_active_id(current_mode):
            self.shortcut_mode_combo.set_active_id(DEFAULT_SHORTCUT_MODE)

        mode_row = PreferenceRow(
            title="Shortcut Mode",
            subtitle="How the shortcut behaves",
            widget=self.shortcut_mode_combo,
        )
        group.add_row(mode_row)

        # Shortcut selection combo
        self.shortcut_combo = Gtk.ComboBoxText()
        self.shortcut_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.shortcut_combo.set_tooltip_text("Select the keyboard shortcut for voice typing")
        _prevent_scroll_on_hover(self.shortcut_combo)

        # Populate shortcut options grouped by side, then a Custom sentinel.
        # Preset and custom are mutually exclusive: only one is active at a time.
        for group_label, shortcut_ids in SHORTCUT_GROUPS.items():
            # Add group separator as a disabled label entry
            separator_id = f"__separator_{group_label}__"
            self.shortcut_combo.append(separator_id, f"── {group_label} ──")
            for shortcut_id in shortcut_ids:
                display_name = SHORTCUT_DISPLAY_NAMES.get(shortcut_id, shortcut_id)
                self.shortcut_combo.append(shortcut_id, display_name)
        self.shortcut_combo.append("__custom__", "Custom Shortcut")

        # Load current shortcut from config
        current_shortcut = self.config_manager.get_str(
            "shortcuts", "toggle_recognition", DEFAULT_SHORTCUT
        )

        self.shortcut_row = PreferenceRow(
            title="Shortcut Key",
            subtitle="Press this key to control voice typing",
            widget=self.shortcut_combo,
        )
        group.add_row(self.shortcut_row)

        # Custom shortcut: modifier+key combos (e.g. Alt+R) for users who want
        # something the preset modifiers can't express (split keyboards, etc.).
        custom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.custom_shortcut_entry = Gtk.Entry()
        self.custom_shortcut_entry.set_placeholder_text("e.g. alt+r")
        self.custom_shortcut_entry.set_width_chars(12)
        self.custom_shortcut_entry.set_tooltip_text(
            "A modifier plus a key, e.g. alt+r, ctrl+alt+r, super+space"
        )
        self.custom_shortcut_entry.connect("activate", self._on_custom_shortcut_apply)
        custom_box.pack_start(self.custom_shortcut_entry, False, False, 0)

        self.record_shortcut_button = Gtk.Button(label="Record")
        self.record_shortcut_button.set_tooltip_text("Click, then press your desired key combo")
        self.record_shortcut_button.connect("clicked", self._on_record_shortcut_clicked)
        custom_box.pack_start(self.record_shortcut_button, False, False, 0)

        self.set_custom_shortcut_button = Gtk.Button(label="Set")
        self.set_custom_shortcut_button.set_tooltip_text("Apply the typed shortcut")
        self.set_custom_shortcut_button.connect("clicked", self._on_custom_shortcut_apply)
        custom_box.pack_start(self.set_custom_shortcut_button, False, False, 0)

        self.custom_shortcut_row = PreferenceRow(
            title="Custom Shortcut",
            subtitle="Modifier + key combo (great for split keyboards)",
            widget=custom_box,
            keywords=("record", "keybinding", "hotkey"),
        )
        # Only shown while "Custom Shortcut" is selected in the preset combo.
        self.custom_shortcut_row.set_no_show_all(True)
        group.add_row(self.custom_shortcut_row)

        # Key-capture state for the Record button.
        self._recording_shortcut = False
        self.connect("key-press-event", self._on_shortcut_key_press)

        self.shortcuts_tab.pack_start(group, False, False, 0)

        # Info box about the shortcut
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.get_style_context().add_class("info-box")
        info_box.set_margin_start(4)
        info_box.set_margin_end(4)
        info_box.set_margin_top(4)

        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.MENU)
        info_box.pack_start(info_icon, False, False, 0)

        self.shortcut_info_label = Gtk.Label(
            label="Changes take effect immediately.",
            xalign=0,
            wrap=True,
        )
        self.shortcut_info_label.get_style_context().add_class("tip-label")
        info_box.pack_start(self.shortcut_info_label, True, True, 0)

        self.shortcuts_tab.pack_start(info_box, False, False, 0)

        # Reflect active shortcut in combo + custom entry (preset vs custom).
        self._sync_shortcut_selection_ui(current_shortcut)

        # Connect signals
        self.shortcut_combo.connect("changed", self._on_shortcut_changed)
        self.shortcut_mode_combo.connect("changed", self._on_shortcut_mode_changed)

        # Update UI based on initial mode
        self._update_shortcut_ui_for_mode(current_mode)

    def _is_preset_shortcut(self, shortcut: str) -> bool:
        """Return True if shortcut is one of the built-in double-tap presets."""
        return shortcut in SUPPORTED_SHORTCUTS

    def _set_custom_shortcut_row_visible(self, visible: bool) -> None:
        """Show or hide the custom shortcut entry / Record / Set controls.

        The row uses ``no_show_all`` so a dialog-level ``show_all()`` does not
        reveal it while a preset is selected. ``Gtk.Widget.show_all()`` is a
        no-op when that flag is set, so clear it before showing (and restore it
        when hiding). Matches the ``language_warning`` pattern of pairing
        ``no_show_all`` with an explicit show path.
        """
        if visible:
            self.custom_shortcut_row.set_no_show_all(False)
            self.custom_shortcut_row.show_all()
        else:
            self.custom_shortcut_row.hide()
            self.custom_shortcut_row.set_no_show_all(True)

    def _set_shortcut_combo_active_id(self, active_id: str) -> None:
        """Select a combo item without firing the changed handler."""
        # Handler may not be connected yet (during section build).
        try:
            self.shortcut_combo.handler_block_by_func(self._on_shortcut_changed)
            blocked = True
        except TypeError:
            blocked = False
        try:
            if not self.shortcut_combo.set_active_id(active_id):
                self.shortcut_combo.set_active_id(DEFAULT_SHORTCUT)
        finally:
            if blocked:
                self.shortcut_combo.handler_unblock_by_func(self._on_shortcut_changed)

    def _sync_shortcut_selection_ui(self, shortcut: str) -> None:
        """Keep preset combo and custom entry mutually exclusive.

        - Preset active: combo shows that preset; custom entry is cleared.
        - Custom active: combo shows "Custom Shortcut"; entry holds the combo string.
        """
        if self._is_preset_shortcut(shortcut):
            self._set_shortcut_combo_active_id(shortcut)
            self.custom_shortcut_entry.set_text("")
            self._set_custom_shortcut_row_visible(False)
        else:
            self._set_shortcut_combo_active_id("__custom__")
            self.custom_shortcut_entry.set_text(shortcut)
            self._set_custom_shortcut_row_visible(True)

    def _report_shortcut_apply_result(self, display_name: str, applied: bool) -> None:
        """Show success/restart feedback after a shortcut change."""
        if applied:
            self.shortcut_info_label.set_markup(
                f"<span foreground='#26a269'>Shortcut updated to <b>{display_name}</b>. "
                "Active now!</span>"
            )
        else:
            self.shortcut_info_label.set_markup(
                f"<i>Shortcut updated to <b>{display_name}</b>. "
                "Restart the app for the change to take full effect.</i>"
            )

    def _apply_custom_shortcut(self, shortcut: str) -> None:
        """Validate, persist, and live-apply a custom shortcut string."""
        shortcut = shortcut.strip().lower()
        if not is_valid_shortcut(shortcut):
            self.shortcut_info_label.set_markup(
                f"<span foreground='#e01b24'>Invalid shortcut: "
                f"<b>{GLib.markup_escape_text(shortcut or '(empty)')}</b>. "
                "Try a modifier + key, e.g. alt+r.</span>"
            )
            return

        # If the user typed/recorded a preset id, treat it as selecting that preset.
        if self._is_preset_shortcut(shortcut):
            self.config_manager.set("shortcuts", "toggle_recognition", shortcut)
            self.config_manager.save_settings()
            self._sync_shortcut_selection_ui(shortcut)
            mode_id = self.shortcut_mode_combo.get_active_id()
            display_name = SHORTCUT_DISPLAY_NAMES.get(shortcut, shortcut)
            logger.info(f"Keyboard shortcut changed to preset via custom entry: {display_name}")
            applied = False
            if self.shortcut_update_callback:
                applied = bool(self.shortcut_update_callback(shortcut, mode_id))
            self._report_shortcut_apply_result(display_name, applied)
            return

        self.config_manager.set("shortcuts", "toggle_recognition", shortcut)
        self.config_manager.save_settings()
        # Dropdown should show Custom, not a leftover preset.
        self._sync_shortcut_selection_ui(shortcut)

        mode_id = self.shortcut_mode_combo.get_active_id()
        display_name = get_shortcut_display_name(shortcut, mode_id)
        logger.info(f"Keyboard shortcut changed to custom: {display_name}")

        applied = False
        if self.shortcut_update_callback:
            applied = bool(self.shortcut_update_callback(shortcut, mode_id))
        self._report_shortcut_apply_result(display_name, applied)

    def _on_custom_shortcut_apply(self, widget):
        """Handle Set button / Entry activation for a typed custom shortcut."""
        if self._initializing:
            return
        self._apply_custom_shortcut(self.custom_shortcut_entry.get_text())

    def _on_record_shortcut_clicked(self, widget):
        """Begin capturing the next key combo pressed in the dialog."""
        self._recording_shortcut = True
        self.record_shortcut_button.set_label("Press keys…")
        self.shortcut_info_label.set_markup(
            "<i>Press a modifier + key (e.g. Alt+R). Press Esc to cancel.</i>"
        )

    def _stop_recording_shortcut(self):
        """Exit key-capture mode and restore the Record button."""
        self._recording_shortcut = False
        self.record_shortcut_button.set_label("Record")

    def _gdk_event_to_shortcut(self, event) -> Optional[str]:
        """Build a canonical shortcut string from a GDK key-press event."""
        modifiers = []
        state = event.state
        if state & Gdk.ModifierType.CONTROL_MASK:
            modifiers.append("ctrl")
        if state & Gdk.ModifierType.MOD1_MASK:
            modifiers.append("alt")
        if state & Gdk.ModifierType.SHIFT_MASK:
            modifiers.append("shift")
        if state & Gdk.ModifierType.SUPER_MASK:
            modifiers.append("super")
        token = _gdk_keyname_to_token(Gdk.keyval_name(event.keyval))
        if not modifiers or token is None:
            return None
        return "+".join(modifiers + [token])

    def _on_shortcut_key_press(self, widget, event):
        """Capture a pressed combo while recording; otherwise pass through."""
        if not getattr(self, "_recording_shortcut", False):
            return False  # not recording: let normal event handling proceed

        keyname = Gdk.keyval_name(event.keyval) or ""
        if keyname in _GDK_MODIFIER_KEYNAMES:
            return True  # wait for the non-modifier key

        shortcut = self._gdk_event_to_shortcut(event)
        if keyname == "Escape" and not shortcut:
            self._stop_recording_shortcut()
            self.shortcut_info_label.set_text("Recording cancelled.")
            return True

        if shortcut and is_valid_shortcut(shortcut):
            self.custom_shortcut_entry.set_text(shortcut)
            self._stop_recording_shortcut()
            self._apply_custom_shortcut(shortcut)
        else:
            self.shortcut_info_label.set_markup(
                "<span foreground='#e01b24'>Need a modifier + key. "
                "Try again or press Esc to cancel.</span>"
            )
        return True

    def _update_shortcut_ui_for_mode(self, mode: str):
        """Update the shortcut UI text to match both the mode and the shortcut.

        A modifier+key combo (e.g. "alt+r") toggles on a single press, not a
        double-tap, so the wording must reflect the active shortcut instead of
        assuming a bare-modifier gesture. Reads the saved shortcut from config
        (the single source of truth for both preset and custom shortcuts).
        """
        shortcut = self.config_manager.get_str("shortcuts", "toggle_recognition", DEFAULT_SHORTCUT)
        is_combo = is_valid_shortcut(shortcut) and parse_shortcut_spec(shortcut).is_combo
        # e.g. "Press Alt+R" (combo toggle), "Double-tap Ctrl", "Hold Alt+R".
        action = get_shortcut_display_name(shortcut, mode)

        if mode == "toggle":
            if is_combo:
                self.shortcut_row.set_subtitle(f"{action} to start/stop voice typing")
                self.shortcut_info_label.set_text(
                    f"In Toggle mode: {action} to start voice typing, {action.lower()} "
                    "again to stop."
                )
            else:
                self.shortcut_row.set_subtitle("Double-tap this key to start/stop voice typing")
                self.shortcut_info_label.set_text(
                    "In Toggle mode: Double-tap the key to start voice typing, "
                    "double-tap again to stop."
                )
        elif mode == "push_to_talk":
            self.shortcut_row.set_subtitle("Hold this shortcut to speak, release to stop")
            self.shortcut_info_label.set_text(
                "In Push-to-Talk mode: Hold the shortcut down to speak, release to stop recording."
            )

    def _on_shortcut_mode_changed(self, widget):
        """Handle shortcut mode selection change."""
        if self._initializing:
            return

        mode_id = self.shortcut_mode_combo.get_active_id()
        if not mode_id:
            return

        # Save to config
        self.config_manager.set("shortcuts", "mode", mode_id)
        self.config_manager.save_settings()

        mode_name = SHORTCUT_MODES.get(mode_id, mode_id)
        logger.info(f"Keyboard shortcut mode changed to: {mode_name}")

        # Update UI to reflect new mode
        self._update_shortcut_ui_for_mode(mode_id)

        # Apply from saved config (source of truth for both preset and custom).
        if self.shortcut_update_callback:
            shortcut_id = self.config_manager.get_str(
                "shortcuts", "toggle_recognition", DEFAULT_SHORTCUT
            )
            success = self.shortcut_update_callback(shortcut_id, mode_id)
            if success:
                self.shortcut_info_label.set_markup(
                    f"<span foreground='#26a269'>Mode updated to <b>{mode_name}</b>. "
                    f"Active now!</span>"
                )
            else:
                self.shortcut_info_label.set_markup(
                    f"<i>Mode updated to <b>{mode_name}</b>. "
                    f"Restart the app for the change to take full effect.</i>"
                )
        else:
            self.shortcut_info_label.set_markup(
                f"<i>Mode updated to <b>{mode_name}</b>. "
                f"Restart the app for the change to take full effect.</i>"
            )

    def _revert_shortcut_combo_to_saved(self) -> None:
        """Restore combo, custom-row visibility, and info text to the saved shortcut.

        Used when the user clicks a group separator in the shortcut combo.
        Must sync the custom row too: selecting Custom Shortcut reveals
        Record/Set, and a separator click must not leave those controls
        visible while a preset is still the active binding. Also clear the
        temporary Record/Set hint so the mode description matches the UI.
        """
        current = self.config_manager.get_str("shortcuts", "toggle_recognition", DEFAULT_SHORTCUT)
        self._sync_shortcut_selection_ui(current)
        mode_id = self.shortcut_mode_combo.get_active_id() or DEFAULT_SHORTCUT_MODE
        self._update_shortcut_ui_for_mode(mode_id)

    def _on_shortcut_changed(self, widget):
        """Handle shortcut selection change."""
        if self._initializing:
            return

        shortcut_id = self.shortcut_combo.get_active_id()
        if not shortcut_id:
            return

        # Ignore separator entries (used for grouped display)
        if shortcut_id.startswith("__separator_"):
            self._revert_shortcut_combo_to_saved()
            return

        # Selecting "Custom Shortcut" does not change the active binding until
        # the user records/sets one; just focus the custom entry for convenience.
        if shortcut_id == "__custom__":
            current = self.config_manager.get_str(
                "shortcuts", "toggle_recognition", DEFAULT_SHORTCUT
            )
            if not self._is_preset_shortcut(current):
                self.custom_shortcut_entry.set_text(current)
            self._set_custom_shortcut_row_visible(True)
            self.custom_shortcut_entry.grab_focus()
            self.shortcut_info_label.set_markup(
                "<i>Record or type a custom shortcut (e.g. alt+r), then click Set.</i>"
            )
            return

        # Preset selected: clear any leftover custom entry so UI matches config.
        self.custom_shortcut_entry.set_text("")
        self._set_custom_shortcut_row_visible(False)
        self.config_manager.set("shortcuts", "toggle_recognition", shortcut_id)
        self.config_manager.save_settings()

        display_name = SHORTCUT_DISPLAY_NAMES.get(shortcut_id, shortcut_id)
        logger.info(f"Keyboard shortcut changed to: {display_name}")

        applied = False
        if self.shortcut_update_callback:
            mode_id = self.shortcut_mode_combo.get_active_id()
            applied = bool(self.shortcut_update_callback(shortcut_id, mode_id))
        self._report_shortcut_apply_result(display_name, applied)

    def _build_sidebar_footer(self, sidebar_box: Gtk.Box):
        """Build the sidebar footer: dictation status, test action, and Close.

        Always visible regardless of the selected page: recognition state,
        live microphone level, a dictation test button, and the dialog's
        in-window Close button. Test output is revealed inline, so any
        instant-applied change can be verified immediately.
        """
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_start(8)
        separator.set_margin_end(8)
        sidebar_box.pack_start(separator, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer.get_style_context().add_class("sidebar-footer")

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.recognition_indicator = Gtk.Image.new_from_icon_name(
            "media-record-symbolic", Gtk.IconSize.MENU
        )
        self.recognition_indicator.set_opacity(0.3)
        status_row.pack_start(self.recognition_indicator, False, False, 0)

        self.recognition_status_label = Gtk.Label(label="Idle", xalign=0)
        self.recognition_status_label.get_style_context().add_class("status-strip-state")
        status_row.pack_start(self.recognition_status_label, False, False, 0)
        footer.pack_start(status_row, False, False, 0)

        # One shared level bar: recognition progress and the microphone test
        # both report into it (recognition_audio_level is a legacy alias).
        self.audio_level_bar = Gtk.LevelBar()
        self.audio_level_bar.set_min_value(0)
        self.audio_level_bar.set_max_value(100)
        self.audio_level_bar.set_value(0)
        self.audio_level_bar.set_valign(Gtk.Align.CENTER)
        self.recognition_audio_level = self.audio_level_bar
        footer.pack_start(self.audio_level_bar, False, False, 0)

        self.test_button = Gtk.Button(label="Test Dictation")
        self.test_button.set_tooltip_text(
            "Record 3 seconds of speech and show the transcription here"
        )
        self.test_button.connect("clicked", self._on_test_clicked)
        footer.pack_start(self.test_button, False, False, 0)

        # One shared status line (audio test results and recognition info)
        self.progress_info_label = Gtk.Label(label="", use_markup=True, xalign=0)
        self.progress_info_label.get_style_context().add_class("status-info")
        self.progress_info_label.set_line_wrap(True)
        self.audio_test_status = self.progress_info_label
        footer.pack_start(self.progress_info_label, False, False, 0)

        # Test transcription output, revealed while testing
        self.test_output_revealer = Gtk.Revealer()
        self.test_output_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_min_content_height(60)
        scrolled_window.set_max_content_height(100)
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.get_style_context().add_class("test-area")

        self.test_textview = Gtk.TextView()
        self.test_textview.set_editable(False)
        self.test_textview.set_cursor_visible(False)
        self.test_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.test_textview.get_style_context().add_class("test-textview")
        self.test_buffer = self.test_textview.get_buffer()
        scrolled_window.add(self.test_textview)
        self.test_output_revealer.add(scrolled_window)

        footer.pack_start(self.test_output_revealer, False, False, 0)

        # Separate Close from the dictation-test controls so it reads as
        # dialog chrome, not as part of Test Dictation (#651).
        close_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        close_separator.set_margin_start(8)
        close_separator.set_margin_end(8)
        close_separator.set_margin_top(2)
        close_separator.set_margin_bottom(2)
        footer.pack_start(close_separator, False, False, 0)

        # In-window Close so the dialog can always be dismissed, even on WMs
        # that hide the title-bar close button for Gtk.Dialog windows (#323).
        close_button = Gtk.Button(label="Close")
        close_button.set_tooltip_text("Close settings (Ctrl+W)")
        close_button.connect("clicked", self._on_close_clicked)
        footer.pack_start(close_button, False, False, 0)

        sidebar_box.pack_start(footer, False, False, 0)

    def _on_close_clicked(self, button):
        """Close the dialog through the normal response path (same as title-bar X)."""
        self.response(Gtk.ResponseType.CLOSE)

    def _build_advanced_section(self):
        """Build the Advanced section with whisper.cpp parameters."""

        # Opt-in toggle at the top of the tab
        opt_in_group = PreferencesGroup(title="Advanced Access")
        self.power_user_switch = Gtk.Switch()
        self.power_user_switch.set_tooltip_text("Reveal advanced whisper.cpp tuning parameters")
        power_user_row = PreferenceRow(
            title="Unlock Advanced Settings",
            subtitle="I know what I'm doing — show me the whisper.cpp tuning knobs",
            widget=self.power_user_switch,
        )
        opt_in_group.add_row(power_user_row)
        self.advanced_tab.pack_start(opt_in_group, False, False, 0)

        # Revealer that hides/shows the actual advanced controls.
        # No inner ScrolledWindow: the notebook tab already scrolls.
        self.advanced_revealer = Gtk.Revealer()
        self.advanced_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

        controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        group = PreferencesGroup(title="Whisper.cpp Decoding")

        self.advanced_no_timestamps_switch = Gtk.Switch()
        self.advanced_no_timestamps_switch.set_tooltip_text(
            "Disable timestamp generation to reduce hallucinations"
        )
        no_timestamps_row = PreferenceRow(
            title="No Timestamps",
            subtitle="Disable timestamp tokens (reduces hallucinations)",
            widget=self.advanced_no_timestamps_switch,
        )
        group.add_row(no_timestamps_row)

        self.advanced_no_context_switch = Gtk.Switch()
        self.advanced_no_context_switch.set_tooltip_text(
            "Do not condition on previously transcribed text"
        )
        no_context_row = PreferenceRow(
            title="No Context",
            subtitle="Prevent error loops from past text",
            widget=self.advanced_no_context_switch,
        )
        group.add_row(no_context_row)

        self.advanced_temperature_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.1)
        self.advanced_temperature_spin.set_digits(1)
        self.advanced_temperature_spin.set_tooltip_text(
            "0.0 = greedy decoding, higher = more random"
        )
        _prevent_scroll_on_hover(self.advanced_temperature_spin)
        temperature_row = PreferenceRow(
            title="Temperature",
            subtitle="Decoding randomness (0.0 = deterministic)",
            widget=self.advanced_temperature_spin,
        )
        group.add_row(temperature_row)

        self.advanced_temperature_inc_spin = Gtk.SpinButton.new_with_range(-1.0, 1.0, 0.1)
        self.advanced_temperature_inc_spin.set_digits(1)
        self.advanced_temperature_inc_spin.set_tooltip_text(
            "-1.0 disables temperature fallback entirely"
        )
        _prevent_scroll_on_hover(self.advanced_temperature_inc_spin)
        temperature_inc_row = PreferenceRow(
            title="Temperature Increment",
            subtitle="Fallback step (-1.0 = disabled)",
            widget=self.advanced_temperature_inc_spin,
        )
        group.add_row(temperature_inc_row)

        self.advanced_entropy_thold_spin = Gtk.SpinButton.new_with_range(0.0, 5.0, 0.1)
        self.advanced_entropy_thold_spin.set_digits(1)
        self.advanced_entropy_thold_spin.set_tooltip_text(
            "Higher values catch more repetition loops"
        )
        _prevent_scroll_on_hover(self.advanced_entropy_thold_spin)
        entropy_row = PreferenceRow(
            title="Entropy Threshold",
            subtitle="Repetition loop detection",
            widget=self.advanced_entropy_thold_spin,
        )
        group.add_row(entropy_row)

        self.advanced_logprob_thold_spin = Gtk.SpinButton.new_with_range(-5.0, 0.0, 0.1)
        self.advanced_logprob_thold_spin.set_digits(1)
        self.advanced_logprob_thold_spin.set_tooltip_text(
            "Average log-probability threshold for fallback"
        )
        _prevent_scroll_on_hover(self.advanced_logprob_thold_spin)
        logprob_row = PreferenceRow(
            title="Logprob Threshold",
            subtitle="Fallback trigger for low confidence",
            widget=self.advanced_logprob_thold_spin,
        )
        group.add_row(logprob_row)

        self.advanced_no_speech_thold_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.advanced_no_speech_thold_spin.set_digits(2)
        self.advanced_no_speech_thold_spin.set_tooltip_text(
            "Probability threshold for treating audio as silence"
        )
        _prevent_scroll_on_hover(self.advanced_no_speech_thold_spin)
        no_speech_row = PreferenceRow(
            title="No-Speech Threshold",
            subtitle="Silence detection confidence",
            widget=self.advanced_no_speech_thold_spin,
        )
        group.add_row(no_speech_row)

        # Initial Prompt -- moved to the end and made multiline
        initial_prompt_help = (
            "Optional. Add names, jargon, punctuation style, or other context to bias "
            "whisper.cpp transcription. Leave blank for normal dictation."
        )
        self.advanced_initial_prompt_textview = Gtk.TextView()
        self.advanced_initial_prompt_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.advanced_initial_prompt_textview.set_tooltip_text(initial_prompt_help)
        self.advanced_initial_prompt_textview.set_size_request(250, 80)

        prompt_scrolled = Gtk.ScrolledWindow()
        prompt_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        prompt_scrolled.set_min_content_height(80)
        prompt_scrolled.set_tooltip_text(initial_prompt_help)
        prompt_scrolled.add(self.advanced_initial_prompt_textview)

        initial_prompt_row = PreferenceRow(
            title="Initial Prompt",
            subtitle="Context to steer transcription style",
            widget=prompt_scrolled,
        )
        initial_prompt_row.set_tooltip_text(initial_prompt_help)
        group.add_row(initial_prompt_row)

        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.get_style_context().add_class("info-box")
        info_box.set_margin_start(4)
        info_box.set_margin_end(4)
        info_box.set_margin_bottom(4)

        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.MENU)
        info_box.pack_start(info_icon, False, False, 0)

        self.advanced_info_label = Gtk.Label(
            label="These settings only apply when the whisper.cpp engine is selected.",
            xalign=0,
            wrap=True,
        )
        self.advanced_info_label.get_style_context().add_class("tip-label")
        info_box.pack_start(self.advanced_info_label, True, True, 0)

        controls_box.pack_start(info_box, False, False, 0)
        controls_box.pack_start(group, False, False, 0)

        # In-page reset action for the decoding parameters above
        self.advanced_reset_button = Gtk.Button(label="Reset to Defaults")
        self.advanced_reset_button.set_tooltip_text(
            "Restore the whisper.cpp advanced parameters to their default values"
        )
        self.advanced_reset_button.connect("clicked", self._on_reset_advanced_clicked)
        reset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        reset_row.set_halign(Gtk.Align.END)
        reset_row.pack_start(self.advanced_reset_button, False, False, 0)
        controls_box.pack_start(reset_row, False, False, 0)

        self.advanced_revealer.add(controls_box)
        self.advanced_tab.pack_start(self.advanced_revealer, False, False, 0)

        self.advanced_no_timestamps_switch.connect("state-set", self._on_advanced_param_changed)
        self.advanced_no_context_switch.connect("state-set", self._on_advanced_param_changed)
        self.advanced_temperature_spin.connect("value-changed", self._on_advanced_param_changed)
        self.advanced_temperature_inc_spin.connect("value-changed", self._on_advanced_param_changed)
        self.advanced_entropy_thold_spin.connect("value-changed", self._on_advanced_param_changed)
        self.advanced_logprob_thold_spin.connect("value-changed", self._on_advanced_param_changed)
        self.advanced_no_speech_thold_spin.connect("value-changed", self._on_advanced_param_changed)

        self.advanced_initial_prompt_buffer = self.advanced_initial_prompt_textview.get_buffer()
        self.advanced_initial_prompt_buffer.connect("changed", self._on_advanced_prompt_changed)

        self.power_user_switch.connect("state-set", self._on_power_user_toggled)

    def _build_about_section(self):
        """Build the About page using the same PreferenceRow cards as other pages."""
        from gi.repository import GdkPixbuf

        from ..utils.resource_manager import ResourceManager

        about_icon = None
        logo_path = ResourceManager().get_icon_path("vocalinux")
        if os.path.exists(logo_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(logo_path)
                scaled = pixbuf.scale_simple(48, 48, GdkPixbuf.InterpType.BILINEAR)
                about_icon = Gtk.Image.new_from_pixbuf(scaled)
                about_icon.set_pixel_size(48)
            except Exception as exc:
                logger.warning("Failed to load About icon: %s", exc)

        app_group = PreferencesGroup(
            title="Vocalinux",
            description=__description__,
            keywords=("about", "version", "app"),
            header_icon=about_icon,
        )

        self.about_version_label = Gtk.Label(label=__version__)
        self.about_version_label.set_selectable(True)
        self.about_version_label.get_style_context().add_class("preference-row-subtitle")
        version_row = PreferenceRow(
            title="Version",
            subtitle="Currently installed Vocalinux build",
            widget=self.about_version_label,
            keywords=("version", "build"),
        )
        app_group.add_row(version_row)

        website_btn = Gtk.Button(label="Open")
        website_btn.set_size_request(100, -1)
        website_btn.set_tooltip_text("Open the Vocalinux GitHub page")
        website_btn.connect("clicked", lambda *_: self._open_web_url(__url__))
        website_row = PreferenceRow(
            title="Website",
            subtitle="Source code, issues, and documentation on GitHub",
            widget=website_btn,
            keywords=("github", "website", "repo"),
        )
        app_group.add_row(website_row)

        license_row = PreferenceRow(
            title="License",
            subtitle=f"GNU AGPL v3 · {__copyright__}",
            keywords=("license", "agpl", "gpl", "copyright"),
        )
        app_group.add_row(license_row)
        self.about_tab.pack_start(app_group, False, False, 0)

        updates_group = PreferencesGroup(
            title="Updates",
            description="Choose a release channel, then check GitHub for a newer build.",
            keywords=("update", "version", "release", "upgrade", "appimage", "nightly", "channel"),
        )

        self.update_channel_combo = Gtk.ComboBoxText()
        self.update_channel_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.update_channel_combo.append("stable", "Stable")
        self.update_channel_combo.append("nightly", "Nightly")
        self.update_channel_combo.set_tooltip_text(
            "Stable uses the latest numbered release. Nightly uses the newest nightly-YYYY-MM-DD build."
        )
        _prevent_scroll_on_hover(self.update_channel_combo)
        saved_channel = normalize_channel(
            self.config_manager.get_str("updates", "channel", DEFAULT_UPDATE_CHANNEL)
        )
        self.update_channel_combo.set_active_id(saved_channel)
        channel_row = PreferenceRow(
            title="Channel",
            subtitle="Stable for releases, Nightly for dated development builds",
            widget=self.update_channel_combo,
            keywords=("channel", "stable", "nightly", "beta"),
        )
        updates_group.add_row(channel_row)

        self.check_updates_btn = Gtk.Button(label="Check")
        self.check_updates_btn.set_size_request(100, -1)
        self.check_updates_btn.set_tooltip_text(
            "Look up the latest release for this channel on GitHub"
        )
        self.check_updates_btn.connect("clicked", self._on_check_updates_clicked)
        self.update_status_row = PreferenceRow(
            title="Status",
            subtitle="Not checked yet",
            widget=self.check_updates_btn,
            keywords=("status", "check"),
        )
        updates_group.add_row(self.update_status_row)

        self.open_release_btn = Gtk.Button(label="Open")
        self.open_release_btn.set_size_request(100, -1)
        self.open_release_btn.set_sensitive(False)
        self.open_release_btn.set_tooltip_text(
            "Open the release page in your browser for download links and install steps"
        )
        self.open_release_btn.connect("clicked", self._on_open_release_clicked)
        self.latest_release_row = PreferenceRow(
            title="Latest Release",
            subtitle="-",
            widget=self.open_release_btn,
            keywords=("latest", "download", "changelog"),
        )
        updates_group.add_row(self.latest_release_row)
        self.about_tab.pack_start(updates_group, False, False, 0)

        self.update_channel_combo.connect("changed", self._on_update_channel_changed)

        self.release_notes_group = PreferencesGroup(
            title="What's New",
            keywords=("changelog", "what's new", "release notes"),
        )
        self.release_notes_row = PreferenceRow(
            title="Release notes",
            subtitle="Notes appear here after a successful update check.",
            keywords=("notes", "changelog"),
        )
        # Allow a longer wrap than typical preference subtitles.
        if self.release_notes_row.subtitle_label is not None:
            self.release_notes_row.subtitle_label.set_max_width_chars(72)
        self.release_notes_group.add_row(self.release_notes_row)
        self.about_tab.pack_start(self.release_notes_group, False, False, 0)
        self.release_notes_group.hide()

    def _set_about_update_badge(self, visible: bool) -> None:
        """Show or hide the green New badge on the About sidebar row."""
        about_page = next((page for page in self._pages if page.name == "about"), None)
        if about_page is None or about_page.update_badge_label is None:
            return
        # Don't fight the search filter's match-count badges.
        searching = bool(self.search_entry.get_text().strip())
        if visible and not searching:
            about_page.update_badge_label.show()
        else:
            about_page.update_badge_label.hide()

    def _seed_pending_update_ui(self) -> None:
        """Apply a tray-discovered update to the About page without another fetch."""
        if self._pending_update is None:
            return
        # Avoid an immediate re-check flicker; user can still press Check.
        self._update_auto_checked = True
        self._apply_update_check_result(
            self._pending_update,
            channel=self._current_update_channel(),
            generation=None,
        )

    def _current_update_channel(self) -> str:
        """Return the selected update channel id."""
        channel_id = self.update_channel_combo.get_active_id()
        return normalize_channel(channel_id or DEFAULT_UPDATE_CHANNEL)

    def _on_update_channel_changed(self, widget):
        """Persist channel choice and refresh the update check."""
        if self._initializing or self._applying_settings:
            return
        channel = self._current_update_channel()
        self.config_manager.set("updates", "channel", channel)
        self.config_manager.save_settings()
        self._start_update_check()

    def _on_check_updates_clicked(self, widget):
        """Manual re-check from the About page."""
        self._start_update_check()

    def _on_open_release_clicked(self, widget):
        """Open the latest or pending release page in the browser."""
        self._open_web_url(self._about_release_url)

    def _start_update_check(self):
        """Kick off a background GitHub release lookup."""
        channel = self._current_update_channel()
        self._update_check_generation += 1
        generation = self._update_check_generation
        self.check_updates_btn.set_sensitive(False)
        self.check_updates_btn.set_label("…")
        self.update_status_row.set_subtitle(f"Checking GitHub ({channel})…")

        # Invalidate any in-flight result; that worker will restart on completion.
        if self._update_check_in_progress:
            return

        self._update_check_in_progress = True
        threading.Thread(
            target=self._update_check_worker,
            args=(channel, generation),
            daemon=True,
        ).start()

    def _update_check_worker(self, channel: str, generation: int):
        """Worker thread: fetch latest release for ``channel`` and compare versions."""
        release = fetch_latest_release(channel=channel)
        GLib.idle_add(self._apply_update_check_result, release, channel, generation)

    def _dialog_is_alive(self) -> bool:
        """Return False when the settings dialog has been destroyed."""
        try:
            # During __init__ (before map) widgets exist but are not realized yet.
            if self._initializing:
                return True
            return bool(self.get_realized())
        except Exception:
            return False

    def _apply_update_check_result(
        self,
        release,
        channel: Optional[str] = None,
        generation: Optional[int] = None,
    ):
        """Update About-page UI from a release lookup result."""
        if not self._dialog_is_alive():
            return False

        channel = normalize_channel(channel or self._current_update_channel())
        current_channel = self._current_update_channel()
        # Drop stale results after a channel switch (or a newer check request).
        if generation is not None and generation != self._update_check_generation:
            self._update_check_in_progress = False
            self._start_update_check()
            return False
        if channel != current_channel:
            self._update_check_in_progress = False
            self._start_update_check()
            return False

        self._update_check_in_progress = False
        self.check_updates_btn.set_sensitive(True)
        self.check_updates_btn.set_label("Check")

        if release is None:
            self._about_release_url = __url__
            missing = "nightly build" if channel == "nightly" else "stable release"
            self.update_status_row.set_subtitle(
                f"Could not find a {missing}. Check your connection, or try again later."
            )
            self.latest_release_row.set_subtitle("Unavailable")
            self.open_release_btn.set_sensitive(True)
            self.open_release_btn.set_tooltip_text("Open the Vocalinux project page")
            self.open_release_btn.get_style_context().remove_class("suggested-action")
            self.release_notes_group.hide()
            # Clear dialog pending state so search restore cannot revive the New
            # badge while About still shows the failed-lookup message. Do not
            # call update_status_callback — tray state stays as-is (same as
            # UpdateMonitor on a failed lookup).
            self._pending_update = None
            self._set_about_update_badge(False)
            return False

        self._about_release_url = (
            release.html_url if is_trusted_release_url(release.html_url) else __url__
        )
        update_available = is_update_available(__version__, release, channel)
        release_label = release.tag_name
        if release.published_at:
            release_label = f"{release.tag_name} · {release.published_at[:10]}"
        if channel == "nightly" and release.prerelease:
            release_label = f"{release_label} (nightly)"

        if update_available:
            self._pending_update = release
            self.update_status_row.set_subtitle(
                f"Update available on {channel} (running {__version__})"
            )
            self.open_release_btn.get_style_context().add_class("suggested-action")
            self._set_about_update_badge(True)
        else:
            self._pending_update = None
            self.update_status_row.set_subtitle(f"Up to date on {channel}")
            self.open_release_btn.get_style_context().remove_class("suggested-action")
            self._set_about_update_badge(False)

        # Keep the tray menu in sync with an About-page check (no extra notification).
        if self.update_status_callback is not None:
            try:
                self.update_status_callback(update_available, release if update_available else None)
            except Exception:
                logger.error("Update status callback failed", exc_info=True)

        self.latest_release_row.set_subtitle(release_label)
        self.open_release_btn.set_sensitive(True)
        self.open_release_btn.set_tooltip_text(
            "Open the release page in your browser for download links and install steps"
        )

        notes = format_release_notes(release.body)
        # Keep the card readable; full notes remain on the release page.
        if len(notes) > 900:
            notes = notes[:900].rstrip() + "…"
        self.release_notes_row.set_subtitle(notes)
        self.release_notes_group.show()
        return False

    def _gpu_acceleration_subtitle(self) -> str:
        """Describe whether the bundled pywhispercpp can use the GPU picker."""
        try:
            from ..speech_recognition.recognition_manager import detect_pywhispercpp_gpu_backend

            bundled = detect_pywhispercpp_gpu_backend()
        except (ImportError, OSError, AttributeError):
            return "Device used by the whisper.cpp engine"
        if bundled == "cpu":
            return "This install has no GPU libraries; whisper.cpp will run on the CPU"
        if bundled == "cuda":
            return "CUDA build uses NVIDIA device 0; this picker applies to Vulkan builds"
        return "Device used by the whisper.cpp Vulkan engine"

    def _build_gpu_section(self):
        """Build the GPU device group on the Performance page.

        Hardware selection, not a decoding knob — so it lives ungated on the
        Performance page rather than behind the power-user unlock.
        """
        gpu_group = PreferencesGroup(title="Hardware Acceleration")
        self.gpu_device_combo = Gtk.ComboBoxText()
        self.gpu_device_combo.set_size_request(_CONTROL_WIDTH, -1)
        self.gpu_device_combo.set_tooltip_text(
            "Select which GPU to use for whisper.cpp Vulkan acceleration. "
            "Has no effect when pywhispercpp was built without GPU libraries."
        )
        _prevent_scroll_on_hover(self.gpu_device_combo)
        self._populate_gpu_devices()
        gpu_row = PreferenceRow(
            title="Vulkan GPU",
            subtitle=self._gpu_acceleration_subtitle(),
            widget=self.gpu_device_combo,
            keywords=("graphics", "hardware", "acceleration", "device"),
        )
        gpu_group.add_row(gpu_row)
        self.power_tab.pack_start(gpu_group, False, False, 0)

        self.gpu_device_combo.connect("changed", self._on_advanced_param_changed)

    def _build_remote_server_section(self):
        """Build the Remote Server configuration section (shown when Remote API engine is selected)."""
        self.remote_server_group = PreferencesGroup(
            title="Remote Server",
            description=(
                "Offload speech recognition to a server on your network. "
                "Supports whisper.cpp and OpenAI-compatible APIs."
            ),
        )

        # Server URL
        self.remote_api_url_entry = Gtk.Entry()
        self.remote_api_url_entry.set_placeholder_text("http://192.168.1.100:8080")
        self.remote_api_url_entry.set_tooltip_text(
            "URL of the remote speech recognition server\n"
            "Supports OpenAI compatible API and whisper.cpp server"
        )
        self.remote_api_url_entry.set_size_request(280, -1)
        remote_url_row = PreferenceRow(
            title="Server URL",
            subtitle="Remote speech recognition server address",
            widget=self.remote_api_url_entry,
        )
        self.remote_server_group.add_row(remote_url_row)

        # API Key
        self.remote_api_key_entry = Gtk.Entry()
        self.remote_api_key_entry.set_placeholder_text("(optional)")
        self.remote_api_key_entry.set_visibility(False)
        self.remote_api_key_entry.set_tooltip_text("API Key for authentication (optional)")
        self.remote_api_key_entry.set_size_request(280, -1)
        remote_key_row = PreferenceRow(
            title="API Key",
            subtitle="Authentication key (optional)",
            widget=self.remote_api_key_entry,
        )
        self.remote_server_group.add_row(remote_key_row)

        # API Endpoint
        self.remote_api_endpoint_combo = Gtk.ComboBoxText()
        self.remote_api_endpoint_combo.set_size_request(280, -1)
        self.remote_api_endpoint_combo.set_tooltip_text(
            "Select the API format of the remote server (API Endpoint Format)"
        )
        self.remote_api_endpoint_combo.append(
            "/v1/audio/transcriptions", "OpenAI/FunASR (/v1/audio/transcriptions)"
        )
        self.remote_api_endpoint_combo.append("/inference", "Whisper.cpp (/inference)")
        _prevent_scroll_on_hover(self.remote_api_endpoint_combo)
        remote_endpoint_row = PreferenceRow(
            title="API Endpoint",
            subtitle="API format for the remote server",
            widget=self.remote_api_endpoint_combo,
        )
        self.remote_server_group.add_row(remote_endpoint_row)

        # Model name
        self.remote_api_model_entry = Gtk.Entry()
        self.remote_api_model_entry.set_placeholder_text("whisper-1")
        self.remote_api_model_entry.set_tooltip_text(
            "Model identifier sent to OpenAI-compatible and FunASR servers"
        )
        self.remote_api_model_entry.set_size_request(280, -1)
        remote_model_row = PreferenceRow(
            title="Model",
            subtitle="Remote model name, for example whisper-1 or sensevoice",
            widget=self.remote_api_model_entry,
        )
        self.remote_server_group.add_row(remote_model_row)

        # Connection test
        self.remote_test_btn = Gtk.Button(label="Test Connection")
        self.remote_test_btn.set_tooltip_text("Test connection to remote server")
        self.remote_test_btn.connect("clicked", self._on_test_remote_connection)
        remote_test_row = PreferenceRow(
            title="Connection Test",
            subtitle="Verify remote server is reachable",
            widget=self.remote_test_btn,
        )
        self.remote_server_group.add_row(remote_test_row)

        self.content_box.pack_start(self.remote_server_group, False, False, 0)

        # Status label below the group
        self.remote_status_label = Gtk.Label(label="", use_markup=True, xalign=0)
        self.remote_status_label.set_margin_start(16)
        self.remote_status_label.set_margin_top(4)
        self.remote_status_label.get_style_context().add_class("status-info")
        self.content_box.pack_start(self.remote_status_label, False, False, 0)

        # Load saved values into the widgets
        saved_url = self.config_manager.get("speech_recognition", "remote_api_url", "")
        saved_key = self.config_manager.get("speech_recognition", "remote_api_key", "")
        saved_endpoint = self.config_manager.get(
            "speech_recognition", "remote_api_endpoint", "/inference"
        )
        saved_model = self.config_manager.get("speech_recognition", "remote_api_model", "whisper-1")
        if saved_url:
            self.remote_api_url_entry.set_text(saved_url)
        if saved_key:
            self.remote_api_key_entry.set_text(saved_key)
        self.remote_api_endpoint_combo.set_active_id(saved_endpoint)
        self.remote_api_model_entry.set_text(saved_model or "whisper-1")

        self.remote_api_url_entry.connect("changed", self._on_remote_api_settings_changed)
        self.remote_api_key_entry.connect("changed", self._on_remote_api_settings_changed)
        self.remote_api_endpoint_combo.connect("changed", self._on_remote_api_settings_changed)
        self.remote_api_model_entry.connect("changed", self._on_remote_api_settings_changed)

        self.remote_server_group.hide()
        self.remote_status_label.hide()

    def _on_power_user_toggled(self, widget, state):
        """Handle the power-user opt-in toggle."""
        if self._initializing or self._applying_settings:
            return False
        if getattr(self, "_power_user_dialog_open", False):
            return True
        if state:
            self._power_user_dialog_open = True
            try:
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=Gtk.DialogFlags.MODAL,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.NONE,
                    text="Advanced Settings",
                )
                dialog.format_secondary_text(
                    "These settings control whisper.cpp's internal decoding parameters. "
                    "Changing them can affect transcription quality and performance. "
                    "Only proceed if you understand the impact."
                )
                dialog.add_button("_Keep it Simple", Gtk.ResponseType.CANCEL)
                confirm_btn = dialog.add_button("_I Know What I'm Doing", Gtk.ResponseType.YES)
                confirm_btn.get_style_context().add_class("suggested-action")
                response = dialog.run()
                dialog.destroy()
            finally:
                self._power_user_dialog_open = False
            if response != Gtk.ResponseType.YES:
                return True
        self.config_manager.set("advanced", "power_user_mode", state)
        self.config_manager.save_settings()
        self.advanced_revealer.set_reveal_child(state)
        return False

    def _on_settings_dialog_response(self, dialog, response_id):
        """Persist deferred text edits before the settings dialog closes."""
        if response_id in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            self._flush_advanced_prompt_if_dirty()

    def _on_advanced_prompt_changed(self, buffer):
        """Track prompt edits without applying settings on every keystroke."""
        if self._initializing or self._applying_settings:
            return
        self._advanced_prompt_dirty = True

    def _flush_advanced_prompt_if_dirty(self):
        """Apply deferred initial prompt edits."""
        if not self._advanced_prompt_dirty or self._initializing or self._applying_settings:
            return
        self._auto_apply_settings()
        self._advanced_prompt_dirty = False

    def _on_advanced_param_changed(self, widget, *args):
        """Handle any advanced parameter change."""
        if self._initializing or self._applying_settings:
            return False
        self._auto_apply_settings()
        self._advanced_prompt_dirty = False
        return False

    def _on_reset_advanced_clicked(self, widget):
        """Reset whisper.cpp advanced parameters to defaults."""
        if self._initializing or self._applying_settings:
            return

        defaults = DEFAULT_CONFIG["advanced"]
        self._applying_settings = True
        try:
            self.advanced_no_timestamps_switch.set_active(defaults["whispercpp_no_timestamps"])
            self.advanced_no_context_switch.set_active(defaults["whispercpp_no_context"])
            self.advanced_initial_prompt_buffer.set_text(defaults["whispercpp_initial_prompt"], -1)
            self.advanced_temperature_spin.set_value(defaults["whispercpp_temperature"])
            self.advanced_temperature_inc_spin.set_value(defaults["whispercpp_temperature_inc"])
            self.advanced_entropy_thold_spin.set_value(defaults["whispercpp_entropy_thold"])
            self.advanced_logprob_thold_spin.set_value(defaults["whispercpp_logprob_thold"])
            self.advanced_no_speech_thold_spin.set_value(defaults["whispercpp_no_speech_thold"])
            self.gpu_device_combo.set_active_id("-1")
        finally:
            self._applying_settings = False

        self._auto_apply_settings()

    def _load_and_apply_settings(self):
        """Load current settings and populate the UI."""
        settings = self._get_current_settings()
        self.current_engine = settings["engine"]
        self.language = settings["language"]
        self.current_model_size = settings["model_size"]
        self.current_vad = settings.get("vad_sensitivity", 3)
        self.current_silence = settings.get("silence_timeout", 2.0)

        logger.info(
            f"Starting dialog with settings: engine={self.current_engine}, model={self.current_model_size}"
        )

        general_settings = self.config_manager.get_settings().get("general", {})
        ui_settings = self.config_manager.get_settings().get("ui", {})
        text_injection_settings = self.config_manager.get_settings().get("text_injection", {})

        autostart_enabled = general_settings.get("autostart", False)
        start_minimized = ui_settings.get("start_minimized", False)
        show_missing_tray_warning = ui_settings.get("show_missing_tray_warning", True)
        copy_to_clipboard = text_injection_settings.get("copy_to_clipboard", False)
        auto_capitalize = text_injection_settings.get("auto_capitalize", True)
        append_trailing_space = text_injection_settings.get("append_trailing_space", True)

        self.autostart_switch.set_active(autostart_enabled)
        self.start_minimized_switch.set_active(start_minimized)
        self.missing_tray_warning_switch.set_active(show_missing_tray_warning)
        self.copy_to_clipboard_switch.set_active(copy_to_clipboard)
        self.auto_capitalize_switch.set_active(auto_capitalize)
        self.append_trailing_space_switch.set_active(append_trailing_space)
        self.sound_effects_switch.set_active(self.config_manager.is_sound_effects_enabled())
        tone_id = self.config_manager.get_sound_effects_tone()
        if not self.sound_tone_combo.set_active_id(tone_id):
            self.sound_tone_combo.set_active_id(DEFAULT_SOUND_EFFECT_TONE)
        self._update_tone_preview_subtitle(self.sound_tone_combo.get_active_id() or tone_id)

        auto_pause_settings = self.config_manager.get_settings().get("auto_pause", {})
        auto_pause_enabled = bool(auto_pause_settings.get("enabled", False))
        self.auto_pause_switch.set_active(auto_pause_enabled)
        self._update_auto_pause_sensitivity(auto_pause_enabled)
        self._refresh_auto_pause_list()

        keepalive_settings = self.config_manager.get_settings().get("model_keepalive", {})
        keepalive_enabled = bool(keepalive_settings.get("enabled", False))
        self.model_keepalive_switch.set_active(keepalive_enabled)
        self._update_model_keepalive_sensitivity(keepalive_enabled)
        timeout_seconds = int(keepalive_settings.get("idle_timeout_seconds", 300) or 300)
        if not self.model_keepalive_timeout_combo.set_active_id(str(timeout_seconds)):
            self.model_keepalive_timeout_combo.set_active_id("300")

        available_engines = get_available_engines()
        available_count = 0

        for engine in ENGINE_MODELS.keys():
            if available_engines.get(engine, False):
                display_name = _engine_display_name(engine)
                self.engine_combo.append(display_name, display_name)
                available_count += 1

        if available_count == 0:
            logger.error("No speech recognition engines available!")
            # Still add them so the UI works, but log the error
            for engine in ENGINE_MODELS.keys():
                display_name = _engine_display_name(engine)
                self.engine_combo.append(display_name, display_name)
        else:
            logger.info(f"Populated {available_count} available engines: {available_engines}")

        if not available_engines.get(self.current_engine, False):
            logger.warning(
                f"Current engine '{self.current_engine}' is not available, "
                "selecting first available"
            )
            for engine in ENGINE_MODELS.keys():
                if available_engines.get(engine, False):
                    self.current_engine = engine
                    break

        engine_text = _engine_display_name(self.current_engine)
        logger.info(f"Setting active engine to: {engine_text}")
        if not self.engine_combo.set_active_id(engine_text):
            logger.warning("Could not set engine by ID, trying by index")
            # Find index of current engine
            model = self.engine_combo.get_model()
            for i, row in enumerate(model):
                if _engine_from_display(row[0]) == self.current_engine:
                    self.engine_combo.set_active(i)
                    break
            else:
                # Fallback to first available
                if self.engine_combo.get_model():
                    self.engine_combo.set_active(0)

        # Populate model and language options for the selected engine
        self._populate_model_options()
        self._sync_language_options_for_selected_model(self.language)

        # Set spin button values
        self.vad_spin.set_value(self.current_vad)
        self.silence_spin.set_value(self.current_silence)

        # Set voice commands switch based on config
        voice_commands_enabled = self.config_manager.is_voice_commands_enabled()
        self.voice_commands_switch.set_active(voice_commands_enabled)

        advanced_settings = self.config_manager.get_settings().get("advanced", {})
        power_user_mode = advanced_settings.get("power_user_mode", False)
        self.power_user_switch.set_active(power_user_mode)
        self.advanced_revealer.set_reveal_child(power_user_mode)
        self.advanced_no_timestamps_switch.set_active(
            advanced_settings.get("whispercpp_no_timestamps", True)
        )
        self.advanced_no_context_switch.set_active(
            advanced_settings.get("whispercpp_no_context", True)
        )
        self.advanced_initial_prompt_buffer.set_text(
            advanced_settings.get("whispercpp_initial_prompt", ""), -1
        )
        self.advanced_temperature_spin.set_value(
            advanced_settings.get("whispercpp_temperature", 0.0)
        )
        self.advanced_temperature_inc_spin.set_value(
            advanced_settings.get("whispercpp_temperature_inc", -1.0)
        )
        self.advanced_entropy_thold_spin.set_value(
            advanced_settings.get("whispercpp_entropy_thold", 2.4)
        )
        self.advanced_logprob_thold_spin.set_value(
            advanced_settings.get("whispercpp_logprob_thold", -1.0)
        )
        self.advanced_no_speech_thold_spin.set_value(
            advanced_settings.get("whispercpp_no_speech_thold", 0.6)
        )

    def _get_current_settings(self):
        """Get current settings from config manager."""
        self.config_manager.load_config()
        settings = self.config_manager.get_settings()

        sr_settings = settings.get("speech_recognition", {})
        engine = sr_settings.get("engine", "vosk")
        language = sr_settings.get("language", "en-us")
        model_size = self.config_manager.get_model_size_for_engine(engine)
        vad_sensitivity = sr_settings.get("vad_sensitivity", 3)
        silence_timeout = sr_settings.get("silence_timeout", 2.0)

        logger.info(
            f"Loaded current settings: engine={engine}, language={language}, model_size={model_size}, "
            f"vad={vad_sensitivity}, silence={silence_timeout}"
        )

        return {
            "engine": engine,
            "language": language,
            "model_size": model_size,
            "vad_sensitivity": vad_sensitivity,
            "silence_timeout": silence_timeout,
        }

    def _get_selected_engine(self) -> str:
        """Return the currently selected engine ID."""
        engine_text = self.engine_combo.get_active_text()
        return _engine_from_display(engine_text) if engine_text else "vosk"

    def _get_selected_whispercpp_model(self) -> str:
        """Return the selected whisper.cpp model variant."""
        variant_id = self.model_variant_combo.get_active_id()
        if variant_id:
            return variant_id

        size_id = self.model_combo.get_active_id()
        model_size = size_id.lower() if size_id else "small"
        variants = get_whispercpp_model_variants(model_size)
        return variants[0] if variants else "small"

    def _get_recommended_whispercpp_model_for_language(self) -> tuple[str, str]:
        """Return the recommended whisper.cpp variant for the selected language."""
        recommended_model, reason = get_recommended_whispercpp_model()
        language_id = self.language_combo.get_active_id() or self.language
        return _recommended_whispercpp_variant_for_language(
            recommended_model,
            reason,
            language_id,
        )

    def _get_default_whispercpp_variant_for_size(self, model_size: str) -> Optional[str]:
        """Return the default specialization for a user-selected size."""
        language_id = self.language_combo.get_active_id() or self.language
        return _default_whispercpp_variant_for_size(model_size, language_id)

    def _is_selected_whispercpp_model_english_only(self) -> bool:
        """Return whether the selected model is a whisper.cpp English-only variant."""
        if self._get_selected_engine() != "whisper_cpp":
            return False
        return is_english_only_whispercpp_model(self._get_selected_whispercpp_model())

    def _set_combo_active_id_or_first(self, combo, active_id: Optional[str]) -> bool:
        """Set a combo to an ID, falling back to the first row."""
        if active_id and combo.set_active_id(active_id):
            return True

        model = combo.get_model()
        if model:
            combo.set_active(0)
            return True
        return False

    def _default_language_for_engine(self, engine: str) -> str:
        """Return a safe default language for the selected engine and model."""
        if engine == "vosk" or self._is_selected_whispercpp_model_english_only():
            return "en-us"
        return "auto"

    def _update_model_picker_tooltips(self):
        """Refresh model picker hover guidance for the current selection."""
        self.model_combo.set_tooltip_text(MODEL_SIZE_TOOLTIP)
        self.model_row.set_tooltip_text(MODEL_SIZE_TOOLTIP)
        self.language_combo.set_tooltip_text(LANGUAGE_TOOLTIP)
        self.language_row.set_tooltip_text(LANGUAGE_TOOLTIP)

        if self._get_selected_engine() == "whisper_cpp":
            specialization_tooltip = _model_specialization_tooltip(
                self._get_selected_whispercpp_model()
            )
        else:
            specialization_tooltip = MODEL_SPECIALIZATION_TOOLTIP

        self.model_variant_combo.set_tooltip_text(specialization_tooltip)
        self.model_variant_row.set_tooltip_text(specialization_tooltip)

    def _sync_language_options_for_selected_model(self, preferred_language: Optional[str] = None):
        """Refresh language options and keep the current model/language pair valid."""
        engine = self._get_selected_engine()
        language_to_keep = (
            preferred_language or self.language_combo.get_active_id() or self.language
        )

        self._processing_language_change = True
        try:
            self._populate_language_options()
            if not self._set_combo_active_id_or_first(self.language_combo, language_to_keep):
                return

            active_language = self.language_combo.get_active_id()
            if active_language != language_to_keep:
                fallback_language = self._default_language_for_engine(engine)
                self._set_combo_active_id_or_first(self.language_combo, fallback_language)

            self.language = (
                self.language_combo.get_active_id() or self._default_language_for_engine(engine)
            )
        finally:
            self._processing_language_change = False

        self._update_language_warning()
        self._update_model_picker_tooltips()

    def _populate_model_options(self):
        """Populate model options based on the current engine selection."""
        self._populating_models = True
        try:
            self.model_combo.remove_all()
            self.model_variant_combo.remove_all()

            engine_text = self.engine_combo.get_active_text()
            if not engine_text:
                logger.warning("No engine selected during model options population")
                return

            engine = _engine_from_display(engine_text)
            logger.info(f"Populating model options for engine: {engine}")

            # Remote API does not need model options
            if engine == "remote_api":
                logger.info("Remote API engine selected, no model options needed")
                return

            saved_model_for_engine = self.config_manager.get_model_size_for_engine(engine)
            logger.info(f"Saved model for {engine}: {saved_model_for_engine}")

            if engine == "whisper_cpp":
                self._populate_whispercpp_model_options(saved_model_for_engine)
                return

            downloaded_models = []
            smallest_model = None
            if engine == "whisper":
                recommended_model, _ = _get_recommended_whisper_model()
            else:
                recommended_model, _ = _get_recommended_vosk_model()

            if engine in ENGINE_MODELS:
                for size in ENGINE_MODELS[engine]:
                    if engine == "whisper" and size in WHISPER_MODEL_INFO:
                        info = WHISPER_MODEL_INFO[size]
                        is_downloaded = _is_whisper_model_downloaded(size)
                    elif engine == "vosk" and size in VOSK_MODEL_INFO:
                        info = VOSK_MODEL_INFO[size]
                        is_downloaded = _is_vosk_model_downloaded(size, self.language)
                    else:
                        is_downloaded = False
                        info = {"size_mb": 0}

                    model_display_name = _model_display_name(size)
                    status = "✓" if is_downloaded else "↓"
                    star = " ★" if size == recommended_model else ""
                    display_text = (
                        f"{model_display_name} ({_format_size(info.get('size_mb', 0))}) "
                        f"{status}{star}"
                    )

                    if is_downloaded:
                        downloaded_models.append(size)
                    if smallest_model is None:
                        smallest_model = size

                    self.model_combo.append(size.capitalize(), display_text)

            # Determine which model to select
            saved_model = saved_model_for_engine.lower()
            valid_models = [m.lower() for m in ENGINE_MODELS.get(engine, [])]

            if saved_model in valid_models:
                model_to_set = saved_model.capitalize()
            elif downloaded_models:
                model_to_set = downloaded_models[0].capitalize()
            else:
                model_to_set = smallest_model.capitalize() if smallest_model else "Small"

            logger.info(f"Setting active model to: {model_to_set}")

            if not self.model_combo.set_active_id(model_to_set):
                logger.warning(f"Could not set model by ID '{model_to_set}'")
                model = self.model_combo.get_model()
                for i, row in enumerate(model):
                    if row[0].lower() == model_to_set.lower():
                        self.model_combo.set_active(i)
                        break
                else:
                    if len(ENGINE_MODELS.get(engine, [])) > 0:
                        self.model_combo.set_active(0)

            logger.info(f"Final selected model: {self.model_combo.get_active_text()}")
        finally:
            self._populating_models = False
            self._refresh_unused_downloads()

    def _populate_whispercpp_model_options(self, saved_model_for_engine: str):
        """Populate whisper.cpp size and specialization selectors."""
        recommended_model, _ = self._get_recommended_whispercpp_model_for_language()
        recommended_size = get_whispercpp_model_size(recommended_model)

        saved_model = saved_model_for_engine.lower()
        if saved_model not in WHISPERCPP_MODEL_INFO:
            saved_model = (
                recommended_model if recommended_model in WHISPERCPP_MODEL_INFO else "tiny"
            )

        saved_size = get_whispercpp_model_size(saved_model)

        for model_size in ENGINE_MODELS["whisper_cpp"]:
            display_text = _model_display_name(model_size)
            if model_size == recommended_size:
                display_text += " ★"
            self.model_combo.append(model_size, display_text)

        self._set_combo_active_id_or_first(self.model_combo, saved_size)
        active_size = self.model_combo.get_active_id() or saved_size
        self._populate_whispercpp_variant_options(active_size, saved_model)

    def _populate_whispercpp_variant_options(
        self,
        model_size: str,
        selected_model: Optional[str] = None,
    ):
        """Populate the whisper.cpp specialization selector for a size."""
        self.model_variant_combo.remove_all()

        variants = get_whispercpp_model_variants(model_size.lower())
        recommended_model, _ = self._get_recommended_whispercpp_model_for_language()

        for model_name in variants:
            info = WHISPERCPP_MODEL_INFO[model_name]
            is_downloaded = is_whispercpp_model_downloaded(model_name)
            status = "✓" if is_downloaded else "↓"
            star = " ★" if model_name == recommended_model else ""
            display_text = (
                f"{_model_specialization_display_name(model_name)} "
                f"({_format_size(info['size_mb'])}) {status}{star}"
            )
            self.model_variant_combo.append(model_name, display_text)

        model_to_set = selected_model if selected_model in variants else None
        if not model_to_set and recommended_model in variants:
            model_to_set = recommended_model
        if not model_to_set:
            model_to_set = self._get_default_whispercpp_variant_for_size(model_size.lower())
        if not model_to_set and variants:
            model_to_set = variants[0]

        self._set_combo_active_id_or_first(self.model_variant_combo, model_to_set)
        self._update_model_picker_tooltips()

    def _active_removable_model_id(self) -> Optional[str]:
        """Return the on-disk id of the model currently selected in Settings."""
        engine = self._get_selected_engine()
        if engine == "whisper_cpp":
            return self._get_selected_whispercpp_model()
        if engine == "whisper":
            model_id = self.model_combo.get_active_id()
            return model_id.lower() if model_id else None
        if engine == "vosk":
            size = (self.model_combo.get_active_id() or "").lower()
            language = self.language_combo.get_active_id() or self.language
            return vosk_model_dirname(size, language)
        return None

    def _list_unused_downloads(self) -> list[tuple[str, str, str]]:
        """Return (id, title, size_label) for unused downloaded models."""
        return [
            (model_id, label, size_label)
            for model_id, label, size_label, in_use in self._list_downloaded_models()
            if not in_use
        ]

    def _list_downloaded_models(self) -> list[tuple[str, str, str, bool]]:
        """Return (id, title, size_label, in_use) for downloaded models."""
        engine = self._get_selected_engine()
        active_id = self._active_removable_model_id()
        items: list[tuple[str, str, str, bool]] = []

        if engine == "whisper_cpp":
            for name in list_downloaded_whispercpp_models():
                info = WHISPERCPP_MODEL_INFO[name]
                size_mb = info["size_mb"] if isinstance(info.get("size_mb"), int) else 0
                items.append(
                    (
                        name,
                        _model_display_name(name),
                        _format_size(size_mb),
                        name == active_id,
                    )
                )
        elif engine == "whisper":
            for name in _list_downloaded_whisper_models():
                info = WHISPER_MODEL_INFO[name]
                size_mb = info["size_mb"] if isinstance(info.get("size_mb"), int) else 0
                items.append(
                    (
                        name,
                        _model_display_name(name),
                        _format_size(size_mb),
                        name == active_id,
                    )
                )
        elif engine == "vosk":
            for model in list_downloaded_vosk_models():
                lang_info = SUPPORTED_LANGUAGES.get(model.language, {})
                lang_name = model.language
                if isinstance(lang_info, dict):
                    name = lang_info.get("name")
                    if isinstance(name, str):
                        lang_name = name
                items.append(
                    (
                        model.dirname,
                        f"{lang_name} · {_model_display_name(model.size)}",
                        _format_size(model.size_mb),
                        model.dirname == active_id,
                    )
                )

        return items

    def _refresh_unused_downloads(self):
        """Rebuild the Unused downloads list, or hide it when empty."""
        if not hasattr(self, "unused_models_group"):
            return

        if self._get_selected_engine() == "remote_api":
            self.unused_models_group.hide()
            return

        unused = self._list_unused_downloads()
        self.unused_models_group.clear_rows()
        if not unused:
            self.unused_models_group.hide()
            return

        count = len(unused)
        leftover = "leftover model" if count == 1 else "leftover models"
        self.unused_expander.set_label(f"Unused downloads ({count} {leftover})")

        was_expanded = self.unused_expander.get_expanded()
        for model_id, title, size_label in unused:
            delete_btn = Gtk.Button(label="Delete")
            delete_btn.set_tooltip_text(f"Delete {title} from disk")
            delete_btn.get_style_context().add_class("destructive-action")
            delete_btn.connect(
                "clicked",
                self._on_unused_download_delete_clicked,
                model_id,
                f"{title} ({size_label})",
            )
            row = PreferenceRow(
                title=title,
                subtitle=size_label,
                widget=delete_btn,
                keywords=("delete", "remove", "unused", "disk", "storage", "downloaded"),
            )
            self.unused_models_group.add_row(row)

        self.unused_models_group.show_all()
        self.unused_expander.set_expanded(was_expanded)
        self._fit_unused_downloads_height()

    def _fit_unused_downloads_height(self):
        """Size the list from the rows it actually holds.

        A per-row estimate cannot know how tall a row renders: with margins and
        a Delete button the rows are taller than the estimate, so the last one
        was cut off below the edge of the viewport while the header still
        counted it (#683).
        """
        _, natural_height = self.unused_models_group.listbox.get_preferred_height()
        self.unused_models_scroll.set_min_content_height(
            min(_UNUSED_DOWNLOADS_MAX_HEIGHT, natural_height)
        )

    def _confirm_model_delete(self, text: str, secondary: str) -> bool:
        """Ask before deleting model files from disk."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=text,
        )
        dialog.format_secondary_text(secondary)
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        delete_btn = dialog.add_button("_Delete", Gtk.ResponseType.YES)
        delete_btn.get_style_context().add_class("destructive-action")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _delete_model_from_disk(self, model_id: str) -> None:
        """Delete a downloaded model for the selected engine."""
        engine = self._get_selected_engine()
        if engine == "whisper_cpp":
            delete_whispercpp_model(model_id)
        elif engine == "whisper":
            _delete_whisper_model(model_id)
        elif engine == "vosk":
            delete_vosk_model(model_id)
        else:
            raise ValueError(f"No local models to delete for engine {engine}")

    def _on_unused_download_delete_clicked(self, widget, model_id: str, label: str):
        """Confirm and delete one unused downloaded model."""
        if model_id == self._active_removable_model_id():
            return
        if not self._confirm_model_delete(
            "Delete unused download?",
            f"{label} will be removed from disk. You can download it again later if needed.",
        ):
            return

        try:
            self._delete_model_from_disk(model_id)
        except (OSError, ValueError, FileNotFoundError) as e:
            logger.error("Failed to delete model %s: %s", model_id, e)
            err = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Could not delete model",
            )
            err.format_secondary_text(str(e))
            err.run()
            err.destroy()
            return

        self._populate_model_options()
        self._update_model_info()

    def _on_engine_changed(self, widget):
        """Handle changes in the selected engine."""
        engine_text = self.engine_combo.get_active_text()
        if not engine_text:
            return

        engine = _engine_from_display(engine_text)

        current_lang = self.language_combo.get_active_id()
        if current_lang:
            if engine == "vosk" and (
                current_lang == "auto" or not SUPPORTED_LANGUAGES.get(current_lang, {}).get("vosk")
            ):
                self.language = "en-us"
            elif engine in ["whisper", "whisper_cpp", "remote_api"] and not current_lang:
                self.language = "auto"

        self._populate_model_options()
        self._sync_language_options_for_selected_model(self.language)
        self._update_engine_specific_ui()
        self._update_model_info()
        self._update_voice_commands_for_engine()

    def _update_voice_commands_for_engine(self):
        """Update voice commands switch based on current engine."""
        sr_config = self.config_manager.get_settings().get("speech_recognition", {})
        voice_commands_enabled = sr_config.get("voice_commands_enabled")

        if voice_commands_enabled is None:
            engine_text = self.engine_combo.get_active_text()
            engine = _engine_from_display(engine_text) if engine_text else "whisper_cpp"
            auto_enabled = engine == "vosk"
            self.voice_commands_switch.set_active(auto_enabled)

    def _on_model_changed(self, widget):
        """Handle changes in the selected model."""
        if self._populating_models:
            return

        if self._get_selected_engine() == "whisper_cpp":
            model_size = self.model_combo.get_active_id()
            if model_size:
                self._populating_models = True
                try:
                    self._populate_whispercpp_variant_options(model_size)
                finally:
                    self._populating_models = False
                self._sync_language_options_for_selected_model()

        self._update_model_info()
        self._refresh_unused_downloads()
        self._auto_apply_settings()

    def _on_model_variant_changed(self, widget):
        """Handle changes in the selected whisper.cpp specialization."""
        if self._populating_models:
            return

        self._sync_language_options_for_selected_model()
        self._update_model_info()
        self._refresh_unused_downloads()
        self._auto_apply_settings()

    def _on_vad_changed(self, widget):
        """Handle changes in VAD sensitivity."""
        self._auto_apply_settings()

    def _on_silence_changed(self, widget):
        """Handle changes in silence timeout."""
        self._auto_apply_settings()

    def _on_voice_commands_toggled(self, widget, state):
        """Handle toggle of the voice commands switch."""
        if self._initializing or self._applying_settings:
            return False

        enabled = bool(state)
        logger.info(f"Voice commands toggled: {enabled}")

        self.config_manager.set("speech_recognition", "voice_commands_enabled", enabled)
        self.config_manager.save_settings()
        try:
            self.speech_engine.reconfigure(voice_commands_enabled=enabled, force_download=False)
        except Exception as e:
            logger.warning(f"Failed to apply voice commands toggle immediately: {e}")
        logger.info(f"Voice commands {'enabled' if enabled else 'disabled'}")
        return False

    def _populate_language_options(self):
        """Populate language dropdown with supported languages."""
        self.language_combo.remove_all()
        engine = self.engine_combo.get_active_text()
        if not engine:
            return

        engine = _engine_from_display(engine)
        english_only_whispercpp = self._is_selected_whispercpp_model_english_only()

        for lang_code, lang_info in SUPPORTED_LANGUAGES.items():
            display_text = lang_info["name"]

            if engine == "vosk":
                has_model = lang_info["vosk"] is not None
                if not has_model or lang_code == "auto":
                    continue
                is_downloaded = _is_vosk_model_downloaded("small", lang_code)
                display_text += " ✓" if is_downloaded else " ↓"
            elif engine in ["whisper", "whisper_cpp", "remote_api"]:
                if english_only_whispercpp and lang_info.get("whisper") != "en":
                    continue
                # Both Whisper and whisper.cpp support auto-detect
                if lang_code == "auto":
                    display_text += " ⚠"
            else:
                continue

            self.language_combo.append(lang_code, display_text)

    def _update_language_warning(self):
        """Update language help text for the selected engine/model/language."""
        lang_code = self.language_combo.get_active_id()
        lang_info = SUPPORTED_LANGUAGES.get(lang_code, {})

        if self._is_selected_whispercpp_model_english_only():
            self.language_warning.set_markup(
                "<span foreground='#e5a50a'>⚠ English-only model selected. "
                "Language choices are limited to English.</span>"
            )
            self.language_warning.show()
        elif lang_info.get("warning"):
            lang_name = lang_info.get("name", "This language")
            self.language_warning.set_markup(
                f"<span foreground='#e5a50a'>⚠ {lang_name}: {lang_info['warning'].lower()}</span>"
            )
            self.language_warning.show()
        else:
            self.language_warning.set_markup("")
            self.language_warning.hide()

    def _on_language_changed(self, widget):
        """Handle language selection change."""
        if self._processing_language_change:
            return

        lang_code = self.language_combo.get_active_id()
        if not lang_code:
            return

        engine = self.engine_combo.get_active_text()
        if not engine:
            return

        self._processing_language_change = True
        try:
            self.language = lang_code
            self._populate_model_options()
            self._update_language_warning()
            self._auto_apply_settings()
        finally:
            self._processing_language_change = False

    def _on_language_entry_activate(self, entry):
        """Commit a unique typed match when Enter is pressed in the language entry."""
        self._commit_or_restore_language_entry()

    def _on_language_entry_focus_out(self, entry, event):
        """Commit or restore the language after the entry loses focus."""
        # Defer so a completion click can set the active id before we restore.
        GLib.idle_add(self._commit_or_restore_language_entry)
        return False

    def _commit_or_restore_language_entry(self) -> bool:
        """Resolve typed language text, or restore the last valid selection."""
        if self._processing_language_change or self._initializing:
            return False
        if self.language_combo.get_active_id():
            return False
        entry = self.language_combo.get_child()
        typed = entry.get_text() if entry is not None else ""
        match_id = _resolve_combo_text_query(typed, _combo_text_rows(self.language_combo))
        if match_id:
            self.language_combo.set_active_id(match_id)
            return False
        # Restoring the same language should not re-apply settings.
        self._processing_language_change = True
        try:
            self._set_combo_active_id_or_first(self.language_combo, self.language)
        finally:
            self._processing_language_change = False
        return False

    def _update_engine_specific_ui(self):
        """Show/hide UI elements driven by the active engine."""
        engine_text = self.engine_combo.get_active_text()
        engine = _engine_from_display(engine_text) if engine_text else "vosk"
        is_remote = engine == "remote_api"

        if is_remote:
            self.model_row.hide()
            self.model_variant_row.hide()
            self.unused_models_group.hide()
            self.model_info_card.hide()
            self.remote_server_group.show_all()
            self.remote_status_label.show()
        else:
            self.model_row.show_all()
            if engine == "whisper_cpp":
                self.model_variant_row.show_all()
            else:
                self.model_variant_row.hide()
            self.remote_server_group.hide()
            self.remote_status_label.hide()

        self._update_model_info()
        self._refresh_unused_downloads()
        self._update_language_warning()
        self._update_model_picker_tooltips()
        self._update_advanced_tab_sensitivity()

    def _update_advanced_tab_sensitivity(self):
        """Enable or disable advanced settings based on selected engine."""
        is_whispercpp = self._get_selected_engine() == "whisper_cpp"

        widgets = [
            self.advanced_no_timestamps_switch,
            self.advanced_no_context_switch,
            self.advanced_initial_prompt_textview,
            self.advanced_temperature_spin,
            self.advanced_temperature_inc_spin,
            self.advanced_entropy_thold_spin,
            self.advanced_logprob_thold_spin,
            self.advanced_no_speech_thold_spin,
            self.advanced_reset_button,
        ]
        for widget in widgets:
            widget.set_sensitive(is_whispercpp)

        if is_whispercpp:
            self.advanced_info_label.set_text("These settings apply to the whisper.cpp engine.")
        else:
            self.advanced_info_label.set_text(
                "These settings only apply when the whisper.cpp engine is selected."
            )

    def _update_model_info(self):
        """Update the model info card display."""
        engine_text = self.engine_combo.get_active_text()
        if not engine_text:
            self.model_info_card.hide()
            return

        engine = _engine_from_display(engine_text)

        if engine == "whisper_cpp":
            model_name = self._get_selected_whispercpp_model()
        else:
            model_id = self.model_combo.get_active_id()
            if not model_id:
                self.model_info_card.hide()
                return
            model_name = model_id.lower()

        if engine == "whisper":
            if model_name not in WHISPER_MODEL_INFO:
                self.model_info_card.hide()
                return
            info = WHISPER_MODEL_INFO[model_name]
            is_downloaded = _is_whisper_model_downloaded(model_name)
            recommended, reason = _get_recommended_whisper_model()
            extra_info = f"Parameters: {info['params']}"
        elif engine == "whisper_cpp":
            if model_name not in WHISPERCPP_MODEL_INFO:
                self.model_info_card.hide()
                return
            info = WHISPERCPP_MODEL_INFO[model_name]
            is_downloaded = is_whispercpp_model_downloaded(model_name)
            recommended, reason = self._get_recommended_whispercpp_model_for_language()
            backend, backend_info = detect_compute_backend()
            extra_info = (
                f"Parameters: {info['params']} • Backend: {get_backend_display_name(backend)}"
            )
        elif engine == "vosk":
            if model_name not in VOSK_MODEL_INFO:
                self.model_info_card.hide()
                return
            info = VOSK_MODEL_INFO[model_name]
            is_downloaded = _is_vosk_model_downloaded(model_name, self.language)
            recommended, reason = _get_recommended_vosk_model()
            extra_info = f"Size: {_format_size(info['size_mb'])}"
        else:
            self.model_info_card.hide()
            return

        model_display_name = _model_display_name(model_name)
        recommended_display_name = _model_display_name(recommended)

        # Update title
        self.model_info_title.set_markup(f"<b>{model_display_name}</b>: {info['desc']}")

        # Update subtitle with status
        if is_downloaded:
            status = "<span foreground='#26a269'>✓ Downloaded and ready</span>"
        else:
            status = f"<span foreground='#e5a50a'>↓ Will download ~{_format_size(info['size_mb'])}</span>"
        self.model_info_subtitle.set_markup(f"{extra_info} • {status}")

        # Update recommendation
        if model_name == recommended:
            self.model_recommendation.set_markup(
                f"<span foreground='#26a269'>★ Recommended for your system ({reason})</span>"
            )
        else:
            self.model_recommendation.set_markup(
                f"Tip: <b>{recommended_display_name}</b> is recommended for your system ({reason})"
            )

        self._update_model_picker_tooltips()
        self.model_info_card.show_all()

    def _auto_apply_settings(self):
        """Automatically apply settings when changed."""
        if self._applying_settings:
            return

        if self._initializing:
            return

        if self._test_active:
            return

        if self._populating_models:
            return

        self._applying_settings = True
        try:
            settings = self.get_selected_settings()
            engine = settings.get("engine", "vosk")
            model_name = settings.get("model_size", "small")

            # Check if model needs to be downloaded
            needs_download = False
            model_info = {"size_mb": 100}  # Default
            if engine == "whisper" and not _is_whisper_model_downloaded(model_name):
                needs_download = True
                model_info = WHISPER_MODEL_INFO.get(model_name, {"size_mb": 500})
            elif engine == "whisper_cpp" and not is_whispercpp_model_downloaded(model_name):
                needs_download = True
                model_info = WHISPERCPP_MODEL_INFO.get(model_name, {"size_mb": 39})
            elif engine == "vosk" and not _is_vosk_model_downloaded(model_name, self.language):
                needs_download = True
                model_info = VOSK_MODEL_INFO.get(model_name, {"size_mb": 50})

            if needs_download:
                logger.info(f"Model {model_name} needs download, showing progress dialog")
                download_dialog = ModelDownloadDialog(
                    self,
                    model_name,
                    model_info["size_mb"],
                    engine=engine,
                    language=self.language,
                )

                def progress_callback(fraction, speed, status):
                    GLib.idle_add(download_dialog.update_progress, fraction, speed, status)

                def download_and_apply():
                    try:
                        self.speech_engine.set_download_progress_callback(progress_callback)

                        def check_cancelled():
                            if download_dialog.cancelled:
                                self.speech_engine.cancel_download()
                            return not download_dialog.cancelled

                        cancel_check_id = GLib.timeout_add(100, check_cancelled)

                        try:
                            self._apply_settings_internal(settings, raise_errors=True)
                            GLib.idle_add(download_dialog.set_complete, True, "")
                            GLib.idle_add(self._populate_model_options)
                        finally:
                            GLib.source_remove(cancel_check_id)
                            self.speech_engine.set_download_progress_callback(None)

                    except Exception as e:
                        error_msg = str(e)
                        if "cancelled" in error_msg.lower():
                            GLib.idle_add(
                                download_dialog.set_complete,
                                False,
                                "Download cancelled",
                            )
                        elif engine == "whisper" and "no module named" in error_msg.lower():
                            GLib.idle_add(
                                download_dialog.set_complete,
                                False,
                                "Whisper not installed",
                            )
                            GLib.idle_add(self._show_whisper_install_dialog)
                        else:
                            GLib.idle_add(download_dialog.set_complete, False, error_msg[:100])

                threading.Thread(target=download_and_apply, daemon=True).start()
                download_dialog.run()
                download_dialog.destroy()
                return

            logger.info(f"Auto-applying settings: {settings}")

            self._save_selected_settings(settings)

            was_running = self.speech_engine.state != RecognitionState.IDLE
            if was_running:
                self.speech_engine.stop_recognition()

            self.speech_engine.reconfigure(**settings)
            logger.info("Settings auto-applied successfully")
        except Exception as e:
            logger.error(f"Failed to auto-apply settings: {e}")
        finally:
            self._applying_settings = False

    def _save_selected_settings(self, settings: dict):
        """Persist selected settings to their appropriate config sections."""
        sr_settings = {k: v for k, v in settings.items() if not k.startswith("whispercpp_")}
        advanced_settings = {k: v for k, v in settings.items() if k.startswith("whispercpp_")}

        self.config_manager.update_speech_recognition_settings(sr_settings)
        for key, value in advanced_settings.items():
            self.config_manager.set("advanced", key, value)
        self.config_manager.save_settings()

    def get_selected_settings(self) -> dict:
        """Return the currently selected settings from the UI."""
        engine_text = self.engine_combo.get_active_text()
        model_id = self.model_combo.get_active_id()
        language_id = self.language_combo.get_active_id()

        engine = _engine_from_display(engine_text) if engine_text else "vosk"
        if engine == "whisper_cpp":
            model_size = self._get_selected_whispercpp_model()
        else:
            model_size = model_id.lower() if model_id else "small"
        language = language_id if language_id else self._default_language_for_engine(engine)

        vad = int(self.vad_spin.get_value())
        silence = self.silence_spin.get_value()

        settings = {
            "engine": engine,
            "model_size": model_size,
            "language": language,
            "vad_sensitivity": vad,
            "silence_timeout": silence,
            "whispercpp_no_timestamps": self.advanced_no_timestamps_switch.get_active(),
            "whispercpp_no_context": self.advanced_no_context_switch.get_active(),
            "whispercpp_initial_prompt": self.advanced_initial_prompt_buffer.get_text(
                self.advanced_initial_prompt_buffer.get_start_iter(),
                self.advanced_initial_prompt_buffer.get_end_iter(),
                False,
            ),
            "whispercpp_temperature": self.advanced_temperature_spin.get_value(),
            "whispercpp_temperature_inc": self.advanced_temperature_inc_spin.get_value(),
            "whispercpp_entropy_thold": self.advanced_entropy_thold_spin.get_value(),
            "whispercpp_logprob_thold": self.advanced_logprob_thold_spin.get_value(),
            "whispercpp_no_speech_thold": self.advanced_no_speech_thold_spin.get_value(),
        }

        gpu_device_id = self.gpu_device_combo.get_active_id()
        if gpu_device_id is not None:
            gpu_device_val = int(gpu_device_id)
            settings["whispercpp_gpu_device"] = None if gpu_device_val == -1 else gpu_device_val

        # Remote API additional settings
        if engine == "remote_api":
            settings["remote_api_url"] = self.remote_api_url_entry.get_text().strip()
            settings["remote_api_key"] = self.remote_api_key_entry.get_text().strip()
            settings["remote_api_endpoint"] = (
                self.remote_api_endpoint_combo.get_active_id() or "/inference"
            )
            settings["remote_api_model"] = (
                self.remote_api_model_entry.get_text().strip() or "whisper-1"
            )

        return settings

    def _on_test_clicked(self, widget):
        """Handle click on the test button."""
        if self._test_active:
            logger.warning("Test already in progress.")
            return

        current_config = self.config_manager.get_settings().get("speech_recognition", {})
        selected_settings = self.get_selected_settings()
        selected_engine = selected_settings.get("engine")
        selected_model = selected_settings.get("model_size")
        # Compare to the live engine too: UI can match the file while the
        # in-memory manager is still on another engine/size (sidecar, pending apply).
        live_engine = getattr(self.speech_engine, "engine", None)
        live_model = getattr(self.speech_engine, "model_size", None)

        settings_differ = False
        if (
            current_config.get("engine") != selected_engine
            or current_config.get("model_size") != selected_model
            or live_engine != selected_engine
            or live_model != selected_model
        ):
            settings_differ = True
        elif selected_engine == "vosk":
            if current_config.get("vad_sensitivity") != selected_settings.get(
                "vad_sensitivity"
            ) or current_config.get("silence_timeout") != selected_settings.get("silence_timeout"):
                settings_differ = True

        if settings_differ:
            self.test_buffer.set_text("Applying settings...")
            if not self.apply_settings():
                self.test_buffer.set_text("Failed to apply settings. Please try again.")
                return
            self.test_buffer.set_text("Settings applied. Starting test...")

        self.connect_to_recognition_manager()

        self._saved_text_callbacks = self.speech_engine.get_text_callbacks()
        self.speech_engine.set_text_callbacks([self._test_text_callback])

        if not self.speech_engine.start_recognition():
            self.speech_engine.set_text_callbacks(self._saved_text_callbacks)
            del self._saved_text_callbacks
            self.test_output_revealer.set_reveal_child(True)
            if getattr(self.speech_engine, "is_auto_paused", False):
                self.test_buffer.set_text(
                    "Dictation is paused. Close the listed app or remove it from "
                    "Auto-Pause settings."
                )
            elif not getattr(self.speech_engine, "model_ready", True):
                self.test_buffer.set_text(
                    "No speech model downloaded. Open the Speech Model page and "
                    "download a model to use Test Dictation."
                )
            else:
                self.test_buffer.set_text("Could not start recognition test.")
            return

        self._test_active = True
        self.test_button.set_sensitive(False)
        self.test_button.set_label("Testing… Speak Now!")
        self.test_output_revealer.set_reveal_child(True)
        self.test_buffer.set_text("")
        self._test_result = ""
        self.update_recognition_progress("Listening", info="Starting recognition test...")

        # Enough room for one utterance plus the configured silence window.
        delay = float(selected_settings.get("silence_timeout", 2.0)) + 2.0
        threading.Thread(target=self._stop_test_after_delay, args=(delay,)).start()

    def _test_text_callback(self, text: str):
        """Callback specifically for the test recognition."""
        GLib.idle_add(self._append_test_result, text)

    def _append_test_result(self, text: str):
        current_text = self.test_buffer.get_text(
            self.test_buffer.get_start_iter(), self.test_buffer.get_end_iter(), False
        )
        separator = " " if current_text.strip() else ""
        self.test_buffer.insert(self.test_buffer.get_end_iter(), separator + text)
        mark = self.test_buffer.get_insert()
        self.test_textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        return False

    def _stop_test_after_delay(self, delay: float):
        """Stops the recognition test after a specified delay."""
        time.sleep(delay)
        GLib.idle_add(self._finalize_test)

    def _finalize_test(self):
        """Finalize the test state and UI updates."""
        if not self._test_active:
            return False

        self.speech_engine.stop_recognition()

        # Wait a bit for any pending transcription to complete before restoring callbacks
        # This ensures the test callback receives the transcription result
        GLib.timeout_add(500, self._restore_callbacks_and_check_result)

        self._test_active = False
        self.test_button.set_sensitive(True)
        self.test_button.set_label("Test Dictation")

        self.update_recognition_progress("Idle")

        return False

    def _restore_callbacks_and_check_result(self):
        """Restore callbacks and check test result after delay."""
        # Restore original text callbacks
        if hasattr(self, "_saved_text_callbacks"):
            self.speech_engine.set_text_callbacks(self._saved_text_callbacks)
            del self._saved_text_callbacks

        # Check result after giving time for final callbacks to complete
        GLib.timeout_add(300, self._check_test_result)
        return False

    def _check_test_result(self):
        """Check if any text was captured after all callbacks have run."""
        final_text = self.test_buffer.get_text(
            self.test_buffer.get_start_iter(), self.test_buffer.get_end_iter(), False
        )
        if not final_text.strip():
            self.test_buffer.set_text("(No speech detected during test)")
        return False

    def _show_whisper_install_dialog(self):
        """Show a dialog with instructions for installing Whisper."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="Whisper Not Installed",
        )

        install_text = """Whisper AI is not installed. To use Whisper for speech recognition, you need to install it first.

Installation Options:

1. Using the installation script:
   ./install.sh --engine=whisper

2. Manual installation in virtual environment:
   source venv/bin/activate
   pip install openai-whisper torch torchaudio

3. If you have SSL issues, try:
   pip install openai-whisper torch torchaudio --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org

Note: Whisper requires significant disk space (~1-3GB) and may take time to download.

For now, the engine has been reverted to VOSK."""

        dialog.format_secondary_text(install_text)
        dialog.run()
        dialog.destroy()

        self.engine_combo.set_active_id("Vosk")
        self._populate_model_options()
        self._update_engine_specific_ui()

    def apply_settings(self):
        """Apply the selected settings."""
        settings = self.get_selected_settings()
        logger.info(f"Applying settings: {settings}")

        engine = settings.get("engine", "vosk")
        model_name = settings.get("model_size", "small")

        needs_download = False
        model_info = {"size_mb": 100}  # Default
        if engine == "whisper" and not _is_whisper_model_downloaded(model_name):
            needs_download = True
            model_info = WHISPER_MODEL_INFO.get(model_name, {"size_mb": 500})
        elif engine == "whisper_cpp" and not is_whispercpp_model_downloaded(model_name):
            needs_download = True
            model_info = WHISPERCPP_MODEL_INFO.get(model_name, {"size_mb": 39})
        elif engine == "vosk" and not _is_vosk_model_downloaded(model_name, self.language):
            needs_download = True
            model_info = VOSK_MODEL_INFO.get(model_name, {"size_mb": 50})

        if needs_download:
            download_dialog = ModelDownloadDialog(
                self,
                model_name,
                model_info["size_mb"],
                engine=engine,
                language=self.language,
            )

            def progress_callback(fraction, speed, status):
                GLib.idle_add(download_dialog.update_progress, fraction, speed, status)

            def download_and_apply():
                try:
                    self.speech_engine.set_download_progress_callback(progress_callback)

                    def check_cancelled():
                        if download_dialog.cancelled:
                            self.speech_engine.cancel_download()
                        return not download_dialog.cancelled

                    cancel_check_id = GLib.timeout_add(100, check_cancelled)

                    try:
                        self._apply_settings_internal(settings, raise_errors=True)
                        GLib.idle_add(download_dialog.set_complete, True, "")
                    finally:
                        GLib.source_remove(cancel_check_id)
                        self.speech_engine.set_download_progress_callback(None)

                except Exception as e:
                    error_msg = str(e)
                    if "cancelled" in error_msg.lower():
                        GLib.idle_add(download_dialog.set_complete, False, "Download cancelled")
                    elif engine == "whisper" and "no module named" in error_msg.lower():
                        GLib.idle_add(download_dialog.set_complete, False, "Whisper not installed")
                        GLib.idle_add(self._show_whisper_install_dialog)
                    else:
                        GLib.idle_add(download_dialog.set_complete, False, error_msg[:100])

            threading.Thread(target=download_and_apply, daemon=True).start()
            download_dialog.run()
            download_dialog.destroy()

            self._populate_model_options()
            return True

        return self._apply_settings_internal(settings)

    def _apply_settings_internal(self, settings: dict, raise_errors: bool = False) -> bool:
        """Internal method to apply settings.

        Args:
            settings: The settings to persist and hand to the engine.
            raise_errors: Re-raise failures instead of showing an error dialog.
                The download threads pass True: their own handlers report the
                failure through the progress dialog, and building a Gtk dialog
                off the main loop is not safe anyway.
        """
        try:
            self._save_selected_settings(settings)

            was_running = self.speech_engine.state != RecognitionState.IDLE
            if was_running:
                self.speech_engine.stop_recognition()
                time.sleep(0.5)

            self.speech_engine.reconfigure(**settings)

            logger.info("Settings applied successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to apply settings: {e}", exc_info=True)
            if raise_errors:
                raise

            if "whisper" in str(e).lower() and "no module named" in str(e).lower():
                self._show_whisper_install_dialog()
            else:
                error_dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Error Applying Settings",
                )
                error_dialog.format_secondary_text(f"Could not apply settings: {e}")
                error_dialog.run()
                error_dialog.destroy()
            return False

    def _populate_gpu_devices(self):
        """Populate the GPU device dropdown with available Vulkan devices."""
        self.gpu_device_combo.remove_all()
        self.gpu_device_combo.append("-1", "Auto (prefer discrete GPU)")

        devices = detect_vulkan_devices()
        for device in devices:
            type_label = device["device_type"].capitalize()
            label = f"[{device['index']}] {device['name']} ({type_label})"
            self.gpu_device_combo.append(str(device["index"]), label)

        saved_device = self.config_manager.get("advanced", "whispercpp_gpu_device", None)
        if saved_device is None:
            self.gpu_device_combo.set_active_id("-1")
        else:
            if not self.gpu_device_combo.set_active_id(str(saved_device)):
                self.gpu_device_combo.set_active_id("-1")

    def _populate_audio_devices(self):
        """Populate the audio device dropdown with available input devices."""
        from ..speech_recognition.recognition_manager import get_audio_input_devices

        self.audio_device_combo.remove_all()

        self.audio_device_combo.append("-1", "System Default")

        devices = get_audio_input_devices()

        for device_index, device_name, is_default in devices:
            label = device_name
            if is_default:
                label += " (default)"
            self.audio_device_combo.append(str(device_index), label)

        saved_device = self.config_manager.get_optional_int("audio", "device_index", None)
        saved_device_name = self.config_manager.get("audio", "device_name", None)

        if saved_device is None:
            self.audio_device_combo.set_active_id("-1")
        else:
            matched_index = _resolve_audio_device_selection(
                devices, saved_device, saved_device_name
            )
            if matched_index is not None:
                self.audio_device_combo.set_active_id(str(matched_index))
                # Migrate legacy configs that stored the UI "(default)" suffix.
                saved_raw_name = _raw_audio_device_name(saved_device_name)
                if saved_device_name and saved_raw_name and saved_device_name != saved_raw_name:
                    self.config_manager.set("audio", "device_name", saved_raw_name)
                    self.config_manager.set("audio", "device_index", matched_index)
                    self.config_manager.save_settings()
            else:
                logger.warning(
                    f"Saved audio device {saved_device} "
                    f"(name: {saved_device_name}) no longer available"
                )
                self.audio_device_combo.set_active_id("-1")
                # Keep combo, config, and engine aligned on System Default.
                self.config_manager.set("audio", "device_index", None)
                self.config_manager.set("audio", "device_name", None)
                self.config_manager.save_settings()
                if self.speech_engine is not None:
                    self.speech_engine.set_audio_device(None, None)

        logger.info(f"Found {len(devices)} audio input devices")

    def _on_refresh_audio_devices(self, widget):
        """Handle refresh button click for audio devices."""
        self._populate_audio_devices()
        self.audio_test_status.set_markup("<i>Device list refreshed</i>")

    def _on_audio_device_changed(self, widget):
        """Handle changes in the selected audio device."""
        if self._initializing:
            return

        device_id = self.audio_device_combo.get_active_id()
        if device_id is None:
            return

        device_index = int(device_id)
        device_label = self.audio_device_combo.get_active_text()
        device_name = _raw_audio_device_name(device_label)

        if device_index == -1:
            self.config_manager.set("audio", "device_index", None)
            self.config_manager.set("audio", "device_name", None)
        else:
            self.config_manager.set("audio", "device_index", device_index)
            self.config_manager.set("audio", "device_name", device_name)

        self.config_manager.save_settings()

        if device_index == -1:
            self.speech_engine.set_audio_device(None, None)
        else:
            self.speech_engine.set_audio_device(device_index, device_name)

        logger.info(f"Audio device changed to: [{device_index}] {device_name}")
        self.audio_test_status.set_markup(f"<i>Selected: {device_label}</i>")

    def _on_test_audio_clicked(self, widget):
        """Handle test audio button click."""
        self.test_audio_btn.set_sensitive(False)
        self.test_audio_btn.set_label("Testing...")
        self.audio_test_status.set_markup("<i>Recording... speak into your microphone</i>")
        self.audio_level_bar.set_value(0)

        device_id = self.audio_device_combo.get_active_id()
        device_index = None if device_id == "-1" else int(device_id)

        def run_test():
            from ..speech_recognition.recognition_manager import test_audio_input

            result = test_audio_input(device_index=device_index, duration=2.0)
            GLib.idle_add(self._handle_audio_test_result, result)

        threading.Thread(target=run_test, daemon=True).start()

    def _handle_audio_test_result(self, result: dict):
        """Handle the result of an audio test."""
        self.test_audio_btn.set_sensitive(True)
        self.test_audio_btn.set_label("Test")

        if result.get("success"):
            max_level = result.get("max_amplitude", 0)
            has_signal = result.get("has_signal", False)
            sample_rate = result.get("sample_rate", 16000)

            level_percent = min(100, (max_level / 327.68))
            self.audio_level_bar.set_value(level_percent)

            # Build sample rate info string
            if sample_rate == 16000:
                rate_info = "(16kHz native)"
            else:
                rate_info = f"({sample_rate // 1000}kHz → 16kHz auto)"

            if has_signal:
                self.audio_test_status.set_markup(
                    f"<span foreground='#26a269'>✓ Audio detected!</span> "
                    f"Peak: {level_percent:.0f}% {rate_info}"
                )
            else:
                self.audio_test_status.set_markup(
                    f"<span foreground='#e5a50a'>⚠ Very low audio level</span> "
                    f"(peak: {level_percent:.1f}%)\n"
                    "<small>Check if microphone is muted or try a different device</small>"
                )
        else:
            error_msg = result.get("error", "Unknown error")
            self.audio_test_status.set_markup(
                f"<span foreground='#c01c28'>✗ Test failed:</span> {error_msg}"
            )

        return False

    def update_recognition_progress(self, state: str, audio_level: float = 0.0, info: str = ""):
        """Update the recognition progress feedback UI."""
        self.recognition_status_label.set_text(state)

        # Remove existing state classes
        for css_class in [
            "recognition-idle",
            "recognition-listening",
            "recognition-processing",
            "recognition-error",
        ]:
            self.recognition_status_label.get_style_context().remove_class(css_class)

        if state == "Listening":
            self.recognition_indicator.set_opacity(1.0)
            self.recognition_status_label.get_style_context().add_class("recognition-listening")
            self.progress_info_label.set_markup("<span foreground='#26a269'>● Listening...</span>")
        elif state == "Processing":
            self.recognition_indicator.set_opacity(1.0)
            self.recognition_status_label.get_style_context().add_class("recognition-processing")
            self.progress_info_label.set_markup(
                "<span foreground='#e5a50a'>● Processing speech...</span>"
            )
        elif state == "Idle":
            self.recognition_indicator.set_opacity(0.3)
            self.recognition_status_label.get_style_context().add_class("recognition-idle")
            self.progress_info_label.set_text("")
        elif state == "Error":
            self.recognition_indicator.set_opacity(0.3)
            self.recognition_status_label.get_style_context().add_class("recognition-error")
            self.progress_info_label.set_markup(
                f"<span foreground='#c01c28'>✗ Error: {info}</span>"
            )
        else:
            self.recognition_indicator.set_opacity(0.3)
            if info:
                self.progress_info_label.set_text(info)

        if audio_level > 0:
            normalized_level = min(100, max(0, audio_level))
            self.recognition_audio_level.set_value(normalized_level)
        elif state == "Idle":
            self.recognition_audio_level.set_value(0)

    def connect_to_recognition_manager(self):
        """Connect to speech recognition manager for progress updates."""
        if hasattr(self, "speech_engine") and self.speech_engine:
            if not hasattr(self, "_callbacks_registered"):
                self.speech_engine.state_callbacks.append(self._on_recognition_state_changed)
                self.speech_engine.register_audio_level_callback(self._on_audio_level_changed)
                self._callbacks_registered = True
                self.connect("destroy", self._on_dialog_destroy)

    def _on_dialog_destroy(self, widget):
        """Clean up callbacks when dialog is destroyed."""
        if hasattr(self, "speech_engine") and self.speech_engine:
            if self._on_recognition_state_changed in self.speech_engine.state_callbacks:
                self.speech_engine.state_callbacks.remove(self._on_recognition_state_changed)
            self.speech_engine.unregister_audio_level_callback(self._on_audio_level_changed)

    def _on_recognition_state_changed(self, state):
        """Handle recognition state changes."""
        state_map = {
            RecognitionState.IDLE: "Idle",
            RecognitionState.LISTENING: "Listening",
            RecognitionState.PROCESSING: "Processing",
            RecognitionState.ERROR: "Error",
        }

        state_str = state_map.get(state, "Unknown")
        GLib.idle_add(self.update_recognition_progress, state_str)

    def _on_audio_level_changed(self, level: float):
        """Handle audio level changes."""
        GLib.idle_add(self.update_recognition_progress, "Listening", level)
