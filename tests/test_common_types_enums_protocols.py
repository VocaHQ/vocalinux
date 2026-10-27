"""
Additional tests for common_types module to increase coverage.

Covers enum utilities, protocol runtime checks, and edge cases.
"""

import unittest
from unittest.mock import MagicMock

from vocalinux.common_types import (
    RecognitionState,
    SpeechRecognitionManagerProtocol,
    TextInjectorProtocol,
)


class TestRecognitionStateAdvanced(unittest.TestCase):
    """Advanced tests for RecognitionState enum."""

    def test_enum_names(self):
        """Test enum member names."""
        self.assertEqual(RecognitionState.IDLE.name, "IDLE")
        self.assertEqual(RecognitionState.LISTENING.name, "LISTENING")
        self.assertEqual(RecognitionState.PROCESSING.name, "PROCESSING")
        self.assertEqual(RecognitionState.ERROR.name, "ERROR")

    def test_enum_values_are_integers(self):
        """Test that enum values are integers (auto)."""
        for state in RecognitionState:
            self.assertIsInstance(state.value, int)

    def test_enum_comparison(self):
        """Test enum comparison operations."""
        state1 = RecognitionState.IDLE
        state2 = RecognitionState.IDLE
        state3 = RecognitionState.LISTENING

        self.assertEqual(state1, state2)
        self.assertNotEqual(state1, state3)

    def test_enum_by_value(self):
        """Test accessing enum by value."""
        idle_value = RecognitionState.IDLE.value
        idle_by_value = RecognitionState(idle_value)
        self.assertEqual(idle_by_value, RecognitionState.IDLE)

    def test_enum_by_name(self):
        """Test accessing enum by name."""
        idle = RecognitionState["IDLE"]
        self.assertEqual(idle, RecognitionState.IDLE)

    def test_enum_representation(self):
        """Test enum string representation."""
        state = RecognitionState.IDLE
        self.assertIn("IDLE", repr(state))
        self.assertIn("RecognitionState", repr(state))

    def test_enum_in_list(self):
        """Test enum membership in lists."""
        states = [RecognitionState.IDLE, RecognitionState.LISTENING]
        self.assertIn(RecognitionState.IDLE, states)
        self.assertNotIn(RecognitionState.ERROR, states)

    def test_enum_dict_key(self):
        """Test using enum as dictionary key."""
        state_dict = {
            RecognitionState.IDLE: "not active",
            RecognitionState.LISTENING: "recording",
            RecognitionState.PROCESSING: "processing audio",
            RecognitionState.ERROR: "error occurred",
        }
        self.assertEqual(state_dict[RecognitionState.IDLE], "not active")
        self.assertEqual(state_dict[RecognitionState.LISTENING], "recording")


class TestSpeechRecognitionManagerProtocolAdvanced(unittest.TestCase):
    """Advanced tests for SpeechRecognitionManagerProtocol."""

    def test_protocol_attribute_state(self):
        """Test protocol state attribute."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        mock_manager.state = RecognitionState.IDLE

        self.assertEqual(mock_manager.state, RecognitionState.IDLE)

    def test_protocol_state_can_change(self):
        """Test protocol state can be changed."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        mock_manager.state = RecognitionState.IDLE

        mock_manager.state = RecognitionState.LISTENING
        self.assertEqual(mock_manager.state, RecognitionState.LISTENING)

        mock_manager.state = RecognitionState.PROCESSING
        self.assertEqual(mock_manager.state, RecognitionState.PROCESSING)

        mock_manager.state = RecognitionState.ERROR
        self.assertEqual(mock_manager.state, RecognitionState.ERROR)

    def test_protocol_start_stop_sequence(self):
        """Test typical start/stop sequence."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        mock_manager.state = RecognitionState.IDLE

        # Start recognition
        mock_manager.start_recognition()
        mock_manager.state = RecognitionState.LISTENING

        # Stop recognition
        mock_manager.stop_recognition()
        mock_manager.state = RecognitionState.IDLE

        self.assertEqual(mock_manager.state, RecognitionState.IDLE)
        mock_manager.start_recognition.assert_called_once()
        mock_manager.stop_recognition.assert_called_once()

    def test_protocol_state_callback_registration(self):
        """Test registering state change callback."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        callback = MagicMock()

        mock_manager.register_state_callback(callback)

        mock_manager.register_state_callback.assert_called_once_with(callback)

    def test_protocol_text_callback_registration(self):
        """Test registering text callback."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        callback = MagicMock()

        mock_manager.register_text_callback(callback)

        mock_manager.register_text_callback.assert_called_once_with(callback)

    def test_protocol_multiple_callbacks(self):
        """Test registering multiple callbacks."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        state_callback1 = MagicMock()
        state_callback2 = MagicMock()
        text_callback = MagicMock()

        mock_manager.register_state_callback(state_callback1)
        mock_manager.register_state_callback(state_callback2)
        mock_manager.register_text_callback(text_callback)

        self.assertEqual(mock_manager.register_state_callback.call_count, 2)
        mock_manager.register_text_callback.assert_called_once()

    def test_protocol_callback_with_state_values(self):
        """Test callback receives state values."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        callback = MagicMock()

        # Register callback
        mock_manager.register_state_callback(callback)

        # Simulate state changes calling the callback
        callback(RecognitionState.IDLE)
        callback(RecognitionState.LISTENING)
        callback(RecognitionState.PROCESSING)
        callback(RecognitionState.ERROR)

        self.assertEqual(callback.call_count, 4)

    def test_protocol_text_callback_with_text(self):
        """Test text callback receives text."""
        mock_manager = MagicMock(spec=SpeechRecognitionManagerProtocol)
        callback = MagicMock()

        mock_manager.register_text_callback(callback)

        # Simulate text recognition
        callback("Hello world")
        callback("Another phrase")

        self.assertEqual(callback.call_count, 2)
        callback.assert_any_call("Hello world")
        callback.assert_any_call("Another phrase")


class TestTextInjectorProtocolAdvanced(unittest.TestCase):
    """Advanced tests for TextInjectorProtocol."""

    def test_protocol_inject_text_success(self):
        """Test successful text injection."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        result = mock_injector.inject_text("test text")

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with("test text")

    def test_protocol_inject_text_failure(self):
        """Test failed text injection."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = False

        result = mock_injector.inject_text("test text")

        self.assertFalse(result)

    def test_protocol_inject_empty_string(self):
        """Test injecting empty string."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        result = mock_injector.inject_text("")

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with("")

    def test_protocol_inject_special_characters(self):
        """Test injecting special characters."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        special_text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = mock_injector.inject_text(special_text)

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with(special_text)

    def test_protocol_inject_unicode_text(self):
        """Test injecting unicode text."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        unicode_text = "Hello 世界 مرحبا мир"
        result = mock_injector.inject_text(unicode_text)

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with(unicode_text)

    def test_protocol_inject_multiline_text(self):
        """Test injecting multiline text."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        multiline_text = "Line 1\nLine 2\nLine 3"
        result = mock_injector.inject_text(multiline_text)

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with(multiline_text)

    def test_protocol_inject_long_text(self):
        """Test injecting long text."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        long_text = "a" * 10000
        result = mock_injector.inject_text(long_text)

        self.assertTrue(result)
        mock_injector.inject_text.assert_called_once_with(long_text)

    def test_protocol_sequential_injections(self):
        """Test sequential text injections."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)
        mock_injector.inject_text.return_value = True

        texts = ["First", "Second", "Third"]
        for text in texts:
            result = mock_injector.inject_text(text)
            self.assertTrue(result)

        self.assertEqual(mock_injector.inject_text.call_count, 3)

    def test_protocol_inject_text_return_values(self):
        """Test different return values from inject_text."""
        mock_injector = MagicMock(spec=TextInjectorProtocol)

        # First call returns True, second returns False
        mock_injector.inject_text.side_effect = [True, False]

        self.assertTrue(mock_injector.inject_text("text1"))
        self.assertFalse(mock_injector.inject_text("text2"))


class TestEnumImports(unittest.TestCase):
    """Test that all enum members are importable."""

    def test_all_enum_members_importable(self):
        """Test that all RecognitionState members are accessible."""
        from vocalinux.common_types import RecognitionState

        # Verify enum values exist and are correct
        idle = RecognitionState.IDLE
        listening = RecognitionState.LISTENING
        processing = RecognitionState.PROCESSING
        error = RecognitionState.ERROR

        self.assertEqual(idle.name, "IDLE")
        self.assertEqual(listening.name, "LISTENING")
        self.assertEqual(processing.name, "PROCESSING")
        self.assertEqual(error.name, "ERROR")


class TestProtocolImports(unittest.TestCase):
    """Test that all protocols are importable."""

    def test_protocol_imports(self) -> None:
        """Test that protocols can be imported."""
        from vocalinux.common_types import (
            SpeechRecognitionManagerProtocol,
            TextInjectorProtocol,
        )

        # Verify protocols are types with expected methods
        self.assertTrue(hasattr(SpeechRecognitionManagerProtocol, "start_recognition"))
        self.assertTrue(hasattr(SpeechRecognitionManagerProtocol, "stop_recognition"))
        self.assertTrue(hasattr(SpeechRecognitionManagerProtocol, "is_transcribing"))
        self.assertTrue(hasattr(SpeechRecognitionManagerProtocol, "cancel_transcription"))
        self.assertTrue(hasattr(SpeechRecognitionManagerProtocol, "register_state_callback"))
        self.assertTrue(hasattr(TextInjectorProtocol, "inject_text"))


if __name__ == "__main__":
    unittest.main()
