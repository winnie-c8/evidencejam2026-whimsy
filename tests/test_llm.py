"""The build-time LLM's text is only used when it passes llm.validate(); no network here."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))
import llm  # noqa: E402


class ValidateTests(unittest.TestCase):
    def test_accepts_numbers_from_the_facts(self):
        self.assertIsNone(llm.validate('Only 123 of 384 combinations were studied.', ['123', '384']))

    def test_rejects_an_invented_number(self):
        self.assertIn('number', llm.validate('About 40 combinations were studied.', ['123']))

    def test_rejects_a_duration(self):
        self.assertIn('duration', llm.validate('Marshes catch up after a decade or so of years.', []))

    def test_rejects_gap_as_negative(self):
        self.assertIn('negative', llm.validate('Grazing is ineffective.', []))

    def test_rejects_empty_markup_and_long(self):
        self.assertEqual(llm.validate('  ', []), 'empty')
        self.assertEqual(llm.validate('<b>x</b>', []), 'markup')
        self.assertEqual(llm.validate('a' * 600, []), 'too long')

    def test_off_without_all_three_variables(self):
        old = {k: os.environ.pop(k, None) for k in ('BRINE_URL', 'BRINE_MODEL', 'BRINE_API_KEY')}
        try:
            os.environ['BRINE_URL'] = 'http://x'
            self.assertFalse(llm.enabled())
        finally:
            os.environ.pop('BRINE_URL', None)
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == '__main__':
    unittest.main()
