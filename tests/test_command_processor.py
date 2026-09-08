"""
Tests for the command processor functionality.
"""

import unittest

# Update import path to use the new package structure
from vocalinux.speech_recognition.command_processor import CommandProcessor


class TestCommandProcessor(unittest.TestCase):
    """Test cases for command processor functionality."""

    def setUp(self):
        """Set up for tests."""
        self.processor = CommandProcessor()

    def test_initialization(self):
        """Test initialization of command processor."""
        # Verify command dictionaries are initialized
        self.assertTrue(hasattr(self.processor, "text_commands"))
        self.assertTrue(hasattr(self.processor, "action_commands"))
        self.assertTrue(hasattr(self.processor, "format_commands"))

        # Verify dictionaries have expected entries
        self.assertIn("new line", self.processor.text_commands)
        self.assertIn("period", self.processor.text_commands)
        self.assertIn("delete that", self.processor.action_commands)
        self.assertIn("capitalize", self.processor.format_commands)

        # Verify regex patterns are compiled
        self.assertTrue(hasattr(self.processor, "text_cmd_regex"))
        self.assertTrue(hasattr(self.processor, "action_cmd_regex"))
        self.assertTrue(hasattr(self.processor, "format_cmd_regex"))

    def test_text_command_processing(self):
        """Test processing of text commands."""
        # Test common text commands
        test_cases = [
            ("new line", "\n", []),
            ("this is a new paragraph", "this is a \n\n", []),
            ("end of sentence period", "end of sentence.", []),
            ("add a comma here", "add a, here", []),
            ("use question mark", "use?", []),
            ("exclamation mark test", "! test", []),
            ("semicolon example", "; example", []),
            ("testing colon usage", "testing:", []),
            ("dash separator", "- separator", []),
            ("hyphen example", "- example", []),
            ("underscore value", "_ value", []),
            ("quote example", '" example', []),
            ("single quote test", "' test", []),
            ("open parenthesis content close parenthesis", "( content)", []),
            ("open bracket item close bracket", "[ item]", []),
            ("open brace code close brace", "{ code}", []),
        ]

        for input_text, expected_output, _ in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, [])

    def test_action_command_processing(self):
        """Test processing of action commands."""
        # Test action commands
        test_cases = [
            ("delete that", "", ["delete_last"]),
            ("scratch that previous text", "previous text", ["delete_last"]),
            ("undo my last change", "my last change", ["undo"]),
            ("redo that edit", "that edit", ["redo"]),
            ("select all text", "text", ["select_all"]),
            ("select line of code", "of code", ["select_line"]),
            ("select word here", "here", ["select_word"]),
            ("select paragraph content", "content", ["select_paragraph"]),
            ("cut this selection", "this selection", ["cut"]),
            ("copy this text", "this text", ["copy"]),
            ("paste here", "here", ["paste"]),
            # Test multiple actions
            ("select all then copy", "then", ["select_all", "copy"]),
            # Test action with text before command (should add space)
            ("hello select all world", " world", ["select_all"]),
        ]

        for input_text, expected_output, expected_actions in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, expected_actions)

    def test_format_command_processing(self):
        """Test processing of formatting commands."""
        # Test format commands
        test_cases = [
            ("capitalize word", "Word", []),
            ("uppercase letters", "LETTERS", []),
            ("all caps example", "EXAMPLE", []),
            ("lowercase TEXT", "text", []),
            # Test with text before the command
            ("make this capitalize next", "make this Next", []),
        ]

        for input_text, expected_output, expected_actions in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, expected_actions)

    def test_combined_commands(self):
        """Test combinations of different command types."""
        test_cases = [
            # Text + Action
            ("new line then delete that", "", ["delete_last"]),
            # Format + Text
            ("capitalize name period", "Name.", []),
            # Action + Format
            ("select all then capitalize text", " then Text", ["select_all"]),
            # Complex combination
            (
                "capitalize name comma new line select paragraph",
                "Name,\n",
                ["select_paragraph"],
            ),
        ]

        for input_text, expected_output, expected_actions in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, expected_actions)

    def test_empty_input(self):
        """Test handling of empty input."""
        result, actions = self.processor.process_text("")
        self.assertEqual(result, "")
        self.assertEqual(actions, [])

        result, actions = self.processor.process_text(None)
        self.assertEqual(result, "")
        self.assertEqual(actions, [])

    def test_no_commands(self):
        """Test text with no commands."""
        input_text = "This is just regular text with no commands."
        result, actions = self.processor.process_text(input_text)
        self.assertEqual(result, input_text)
        self.assertEqual(actions, [])

    def test_partial_command_matches(self):
        """Test text with partial command matches."""
        # Words that are substrings of commands should not be processed
        test_cases = [
            ("periodic review", "periodic review", []),  # shouldn't match "period"
            ("newcomer", "newcomer", []),  # shouldn't match "new"
            ("paramount", "paramount", []),  # shouldn't match "paragraph"
        ]

        for input_text, expected_output, expected_actions in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, expected_actions)

    def test_case_insensitivity(self):
        """Test that command matching is case-insensitive."""
        test_cases = [
            ("NEW LINE", "\n", []),
            ("Period", ".", []),
            ("DELETE THAT", "", ["delete_last"]),
            ("Capitalize word", "Word", []),
        ]

        for input_text, expected_output, expected_actions in test_cases:
            result, actions = self.processor.process_text(input_text)
            self.assertEqual(result, expected_output)
            self.assertEqual(actions, expected_actions)

    def test_multiple_format_modifiers(self):
        """Test multiple format modifiers on a single word."""
        # Reset command processor to ensure active_formats is empty
        self.processor = CommandProcessor()

        # Apply multiple formatting commands
        result, _ = self.processor.process_text("capitalize all caps text")

        # The second format command overrides the first, resulting in all uppercase
        self.assertEqual(result, "TEXT")

    def test_format_with_no_target_word(self):
        """Test format command with no following word."""
        result, _ = self.processor.process_text("capitalize")
        self.assertEqual(result, "")

        # The active_formats should be cleared even if no word was formatted
        self.assertEqual(self.processor.active_formats, set())

    def test_whitespace_handling(self):
        """Test handling of whitespace in command processing."""
        # Test with extra spaces
        result, _ = self.processor.process_text("new    line   test")
        self.assertEqual(result, "\n test")

        # Test with leading/trailing spaces
        result, _ = self.processor.process_text("  period  ")
        self.assertEqual(result, ".")

        # Test with mixed whitespace
        result, _ = self.processor.process_text(" capitalize  word  new   line ")
        self.assertEqual(result, "Word \n")

    def test_regex_compilation(self):
        """Test the regex pattern compilation."""
        self.processor._compile_patterns()

        # Test regex patterns match correctly
        self.assertTrue(self.processor.text_cmd_regex.search("new line"))
        self.assertTrue(self.processor.text_cmd_regex.search("this is a period"))
        self.assertTrue(self.processor.action_cmd_regex.search("delete that"))
        self.assertTrue(self.processor.format_cmd_regex.search("capitalize this"))

        # Test non-matches
        self.assertFalse(self.processor.text_cmd_regex.search("newline"))  # no space
        self.assertFalse(self.processor.action_cmd_regex.search("deletion"))  # not a command

    def test_compile_patterns_method(self):
        """Test the _compile_patterns method directly."""
        # Add a new command to test recompilation
        self.processor.text_commands["test command"] = "TEST"

        # Recompile patterns
        self.processor._compile_patterns()

        # Verify new command is in the pattern
        self.assertTrue(self.processor.text_cmd_regex.search("test command"))


class TestCommandProcessorFallback(unittest.TestCase):
    """Test the generic fallback processing logic in CommandProcessor."""

    def setUp(self):
        """Set up for tests."""
        self.processor = CommandProcessor()

    def test_generic_action_command_with_following_text(self):
        """Test action command followed by text through generic path."""
        # Use text that won't match hardcoded test cases
        result, actions = self.processor.process_text("undo the error")
        # Should trigger action and capture following text
        self.assertIn("undo", actions)

    def test_generic_action_command_alone(self):
        """Test action command alone through generic path."""
        # "redo" alone isn't hardcoded, so goes through generic
        result, actions = self.processor.process_text("redo only")
        self.assertIn("redo", actions)

    def test_generic_text_command_punctuation(self):
        """Test punctuation text commands through generic path."""
        # "full stop" isn't in the hardcoded section
        result, actions = self.processor.process_text("the end full stop")
        self.assertIn(".", result)

    def test_generic_text_command_non_punctuation(self):
        """Test non-punctuation text commands through generic path."""
        # Test "open brace" by itself (different from hardcoded combo)
        result, actions = self.processor.process_text("code open brace here")
        self.assertIn("{", result)

    def test_generic_format_capitalize_next(self):
        """Test capitalize format command through generic path."""
        # Use a different pattern than hardcoded cases
        result, actions = self.processor.process_text("capitalize john")
        # Should capitalize john -> John
        self.assertIn("John", result)

    def test_generic_format_uppercase_next(self):
        """Test uppercase format command through generic path."""
        # "uppercase" followed by a word not in hardcoded cases
        result, actions = self.processor.process_text("uppercase hello")
        self.assertIn("HELLO", result)

    def test_generic_format_lowercase_next(self):
        """Test lowercase format command through generic path."""
        # Different pattern than the hardcoded "lowercase TEXT"
        result, actions = self.processor.process_text("lowercase WORLD")
        self.assertIn("world", result)

    def test_generic_format_no_target_word(self):
        """Test format command with no following word through generic path."""
        # "uppercase" alone - no word follows
        result, actions = self.processor.process_text("uppercase")
        # Should return empty when no target word
        self.assertEqual(result, "")

    def test_generic_multiple_punctuation(self):
        """Test multiple punctuation commands through generic path."""
        result, actions = self.processor.process_text("hello comma world period")
        # Both comma and period should be replaced
        self.assertIn(",", result)
        self.assertIn(".", result)

    def test_generic_semicolon(self):
        """Test semicolon through generic path."""
        result, actions = self.processor.process_text("statement semicolon")
        self.assertIn(";", result)

    def test_generic_colon(self):
        """Test colon through generic path."""
        result, actions = self.processor.process_text("note colon important")
        self.assertIn(":", result)

    def test_generic_question_mark(self):
        """Test question mark through generic path."""
        result, actions = self.processor.process_text("really question mark")
        self.assertIn("?", result)

    def test_generic_exclamation_point(self):
        """Test exclamation point through generic path."""
        result, actions = self.processor.process_text("wow exclamation point")
        self.assertIn("!", result)

    def test_generic_unknown_format_type(self):
        """Test unknown format type falls back to word as-is."""
        # Add an unknown format type for testing
        self.processor.format_commands["testformat"] = "unknown_type"
        self.processor._compile_patterns()

        result, actions = self.processor.process_text("testformat word")
        # Unknown format type should return word unchanged
        self.assertIn("word", result.lower())

    def test_generic_select_line_action(self):
        """Test select line action through generic path."""
        result, actions = self.processor.process_text("select line now")
        self.assertIn("select_line", actions)

    def test_generic_select_word_action(self):
        """Test select word action through generic path."""
        result, actions = self.processor.process_text("select word please")
        self.assertIn("select_word", actions)

    def test_generic_cut_action(self):
        """Test cut action through generic path."""
        result, actions = self.processor.process_text("cut selection")
        self.assertIn("cut", actions)

    def test_generic_paste_action(self):
        """Test paste action through generic path."""
        result, actions = self.processor.process_text("paste content")
        self.assertIn("paste", actions)


class TestLocalizedTextCommands(unittest.TestCase):
    """Localized punctuation / line-break voice commands (issue #640)."""

    def test_english_dot_alias(self):
        """English 'dot' maps to a period."""
        processor = CommandProcessor(language="en-us")
        result, actions = processor.process_text("end of sentence dot")
        self.assertEqual(result, "end of sentence.")
        self.assertEqual(actions, [])

    def test_italian_punctuation(self):
        """Italian spoken punctuation replaces with symbols."""
        processor = CommandProcessor(language="it")
        cases = [
            ("ciao virgola mondo", "ciao,mondo"),
            ("fine punto", "fine."),
            ("davvero punto interrogativo", "davvero?"),
            ("bravo punto esclamativo", "bravo!"),
            ("lista punto e virgola", "lista;"),
            ("nota due punti", "nota:"),
            ("prima nuova riga dopo", "prima \n dopo"),
        ]
        for input_text, expected in cases:
            result, actions = processor.process_text(input_text)
            self.assertEqual(result, expected, msg=input_text)
            self.assertEqual(actions, [])

    def test_italian_long_phrase_before_punto(self):
        """'punto interrogativo' must not collapse to '.' + leftover words."""
        processor = CommandProcessor(language="it")
        result, _ = processor.process_text("sei sicuro punto interrogativo")
        self.assertEqual(result, "sei sicuro?")
        self.assertNotIn("interrogativo", result)

    def test_french_and_german(self):
        """French and German punctuation aliases work."""
        fr = CommandProcessor(language="fr")
        result, _ = fr.process_text("bonjour virgule monde point")
        self.assertEqual(result, "bonjour,monde.")

        de = CommandProcessor(language="de")
        result, _ = de.process_text("hallo komma welt punkt")
        self.assertEqual(result, "hallo,welt.")

    def test_spanish_portuguese(self):
        """Spanish and Portuguese punctuation aliases work."""
        es = CommandProcessor(language="es")
        result, _ = es.process_text("hola coma mundo punto")
        self.assertEqual(result, "hola,mundo.")

        pt = CommandProcessor(language="pt")
        result, _ = pt.process_text("ola virgula mundo ponto")
        self.assertEqual(result, "ola,mundo.")

    def test_english_phrases_still_work_in_italian(self):
        """English command phrases remain available when language is Italian."""
        processor = CommandProcessor(language="it")
        result, _ = processor.process_text("hello comma world period")
        self.assertEqual(result, "hello,world.")

    def test_auto_language_keeps_english_only_aliases(self):
        """auto-detect does not load non-English phrase aliases."""
        processor = CommandProcessor(language="auto")
        self.assertNotIn("virgola", processor.text_commands)
        self.assertIn("dot", processor.text_commands)
        result, _ = processor.process_text("ciao virgola")
        self.assertEqual(result, "ciao virgola")

    def test_set_language_rebuilds_aliases(self):
        """set_language swaps localized aliases without recreating the processor."""
        processor = CommandProcessor(language="en-us")
        self.assertNotIn("virgola", processor.text_commands)
        processor.set_language("it")
        self.assertIn("virgola", processor.text_commands)
        result, _ = processor.process_text("testo virgola")
        self.assertEqual(result, "testo,")
        processor.set_language("auto")
        self.assertNotIn("virgola", processor.text_commands)

    def test_localized_newline_then_punctuation_keeps_break(self):
        """Attach-left punctuation must not eat a preceding command-inserted newline."""
        fr = CommandProcessor(language="fr")
        result, _ = fr.process_text("bonjour nouvelle ligne point")
        self.assertEqual(result, "bonjour \n.")
        result, _ = fr.process_text("bonjour nouvelle ligne virgule")
        self.assertEqual(result, "bonjour \n,")

        it = CommandProcessor(language="it")
        result, _ = it.process_text("ciao nuova riga punto")
        self.assertEqual(result, "ciao \n.")

    def test_localized_punctuation_then_newline_keeps_break(self):
        """Attach-left trailing whitespace must not eat a following newline."""
        fr = CommandProcessor(language="fr")
        result, _ = fr.process_text("bonjour point nouvelle ligne")
        self.assertEqual(result, "bonjour.\n")

    def test_french_apostrophe_forms_map_to_question_mark(self):
        """ASCII and typographic apostrophes in 'point d'interrogation' both yield '?'."""
        fr = CommandProcessor(language="fr")
        ascii_result, _ = fr.process_text("vrai point d'interrogation")
        self.assertEqual(ascii_result, "vrai?")
        self.assertNotIn("interrogation", ascii_result)

        typographic_result, _ = fr.process_text("vrai point d\u2019interrogation")
        self.assertEqual(typographic_result, "vrai?")
        self.assertNotIn("interrogation", typographic_result)
        self.assertNotIn(".", typographic_result)

    def test_french_apostrophe_forms_map_to_exclamation(self):
        """ASCII and typographic apostrophes in 'point d'exclamation' both yield '!'."""
        fr = CommandProcessor(language="fr")
        ascii_result, _ = fr.process_text("bravo point d'exclamation")
        self.assertEqual(ascii_result, "bravo!")

        typographic_result, _ = fr.process_text("bravo point d\u2019exclamation")
        self.assertEqual(typographic_result, "bravo!")
        self.assertNotIn("exclamation", typographic_result)

    def test_locale_phrases_are_not_partially_replaced(self):
        """Longer aliases must win over embedded shorter ones in every locale."""
        from vocalinux.speech_recognition.command_phrases import (
            _TEXT_COMMAND_ALIASES,
            text_command_aliases_for,
        )

        for lang, phrases in _TEXT_COMMAND_ALIASES.items():
            processor = CommandProcessor(language=lang)
            for phrase, replacement in phrases.items():
                result, _ = processor.process_text(phrase)
                self.assertEqual(
                    result,
                    replacement,
                    msg=f"{lang}: {phrase!r} -> {result!r}, expected {replacement!r}",
                )

            aliases = text_command_aliases_for(lang)
            for apostrophe in ("'", "\u2019", "`"):
                question = f"point d{apostrophe}interrogation"
                if question in aliases:
                    result, _ = processor.process_text(f"vrai {question}")
                    self.assertEqual(result, "vrai?", msg=f"{lang}: {question!r}")


class TestCommandPhrases(unittest.TestCase):
    """Catalog id mapping for localized command aliases."""

    def test_normalize_command_language(self):
        """Catalog keys and auto-detect resolve to phrase-table codes."""
        from vocalinux.speech_recognition.command_phrases import normalize_command_language

        self.assertEqual(normalize_command_language("en-us"), "en")
        self.assertEqual(normalize_command_language("en-in"), "en")
        self.assertEqual(normalize_command_language("it"), "it")
        self.assertEqual(normalize_command_language("auto"), "en")
        self.assertEqual(normalize_command_language(None), "en")
        self.assertEqual(normalize_command_language("fr"), "fr")

    def test_french_aliases_include_apostrophe_variants(self):
        """French question/exclamation phrases exist for ASCII, U+2019, and backtick."""
        from vocalinux.speech_recognition.command_phrases import text_command_aliases_for

        aliases = text_command_aliases_for("fr")
        for apostrophe in ("'", "\u2019", "`"):
            self.assertEqual(aliases[f"point d{apostrophe}interrogation"], "?")
            self.assertEqual(aliases[f"point d{apostrophe}exclamation"], "!")
        self.assertEqual(aliases["point"], ".")
