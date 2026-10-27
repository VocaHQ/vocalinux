"""Tests for optional speech-engine availability checks."""

import sys
import unittest
from importlib.machinery import ModuleSpec
from unittest.mock import patch

from vocalinux.speech_recognition import engines


class TestEngineAvailability(unittest.TestCase):
    def test_module_specs_control_availability_without_importing(self) -> None:
        module_names = ("vosk", "whisper", "faster_whisper")
        for available_modules in (set(module_names), set()):
            with self.subTest(available_modules=available_modules):
                with patch.dict(sys.modules):
                    for module_name in module_names:
                        sys.modules.pop(module_name, None)

                    def find_spec(name: str) -> ModuleSpec | None:
                        if name in available_modules:
                            return ModuleSpec(name, loader=None)
                        return None

                    with patch.object(
                        engines.importlib.util,
                        "find_spec",
                        side_effect=find_spec,
                    ):
                        available = engines.available_engines()

                    for module_name in module_names:
                        self.assertEqual(
                            module_name in available,
                            module_name in available_modules,
                        )
                        self.assertNotIn(module_name, sys.modules)

    def test_module_availability_handles_spec_errors(self) -> None:
        for error in (ImportError, ValueError):
            with self.subTest(error=error):
                with patch.object(engines.importlib.util, "find_spec", side_effect=error):
                    self.assertFalse(engines._module_available("missing"))
