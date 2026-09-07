"""Turn what the user actually knows into a model choice (#779).

The Speech Model panel asks four questions, but only two of them are answerable
without knowing the hardware: what language you speak, and whether you want it
faster or more accurate. Size follows from the machine, and the specialization
follows from the language. These helpers do the size half; the language half is
the variant derivation that already lives in the settings dialog.

Priority is expressed relative to what the hardware detection recommends rather
than as an absolute size, so "most accurate" means something different on a
laptop and on a workstation, which is the point.
"""

from .whispercpp_model_info import MODEL_SIZES

FASTEST = "fastest"
BALANCED = "balanced"
ACCURATE = "accurate"

PRIORITIES = (FASTEST, BALANCED, ACCURATE)

PRIORITY_LABELS = {
    FASTEST: "Fastest",
    BALANCED: "Balanced",
    ACCURATE: "Most accurate",
}

# How far to move from the hardware recommendation, in size steps.
_PRIORITY_OFFSET = {FASTEST: -1, BALANCED: 0, ACCURATE: 1}


def _clamp(index: int) -> int:
    return max(0, min(len(MODEL_SIZES) - 1, index))


def size_for_priority(recommended_size: str, priority: str) -> str:
    """Return the size a priority asks for, relative to the recommendation."""
    if recommended_size not in MODEL_SIZES:
        recommended_size = MODEL_SIZES[0]
    offset = _PRIORITY_OFFSET.get(priority, 0)
    return MODEL_SIZES[_clamp(MODEL_SIZES.index(recommended_size) + offset)]


def priority_for_size(recommended_size: str, size: str) -> str:
    """Return the priority that best describes an already-chosen size.

    Used to open simple mode showing the truth about the current configuration
    instead of resetting it, so switching modes never silently changes the model.
    """
    if recommended_size not in MODEL_SIZES or size not in MODEL_SIZES:
        return BALANCED

    delta = MODEL_SIZES.index(size) - MODEL_SIZES.index(recommended_size)
    if delta < 0:
        return FASTEST
    if delta > 0:
        return ACCURATE
    return BALANCED
