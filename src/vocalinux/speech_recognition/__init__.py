"""
Speech recognition module for Vocalinux
"""

from . import command_processor, dictionary_corrector, recognition_manager  # noqa: F401


def get_audio_input_devices():
    """Get available audio input devices."""
    return recognition_manager.get_audio_input_devices()


def test_audio_input(device_index=None, duration=1.0):
    """Test audio input from a device."""
    return recognition_manager.test_audio_input(device_index, duration)
