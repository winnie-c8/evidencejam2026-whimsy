"""The build-time LLM's text is only used when it passes llm.validate(); no network here."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))
import llm  # noqa: E402


class ClaimTests(unittest.TestCase):
    """Hard rule 1: a reply may not flip a direction or certainty from the pack."""
    @classmethod
    def setUpClass(cls):
        import load
        cls.data = load.load_all(os.path.join(os.path.dirname(__file__), '..', 'answers'))

    def check(self, qid, text):
        _, nums, fl = llm.facts(self.data, self.data.questions[qid])
        return llm.validate(text, nums, fl)

    def test_faithful_reply_passes(self):
        self.assertIsNone(self.check('q1', 'With high certainty, seedling size and stock type and vegetation control '
                                     'and release help growth, while competing vegetation lowers survival.'))
        self.assertIsNone(self.check('q3', 'All 10 of the most-studied combinations have mixed results.'))

    def test_flipped_direction_rejected(self):
        self.assertIn('direction', self.check('q1', 'With high certainty, competing vegetation increases survival.'))
        self.assertIn('direction', self.check('q3', 'The most-studied combinations increase plant cover.'))

    def test_raised_or_lowered_certainty_rejected(self):
        self.assertIn('certainty', self.check('q1', 'Seedling size helps, with low certainty.'))

    def test_unnamed_claim_rejected(self):
        self.assertIn('without naming', self.check('q2', 'The studies cannot say how long. Created marshes match '
                                                         'natural ones on biodiversity.'))

    def test_certainty_belongs_to_the_item_named_next_to_it(self):
        ok = ('The studies cannot say how long. Created marshes lag natural ones on growth, size and biomass '
              '(high certainty) and species richness and diversity (moderate certainty).')
        self.assertIsNone(self.check('q2', ok))
        swapped = ('The studies cannot say how long. Created marshes lag natural ones on growth, size and biomass '
                   '(moderate certainty) and species richness and diversity (high certainty).')
        self.assertIn('certainty', self.check('q2', swapped))
        # site preparation is mixed, so "with high certainty ... help" can't cover it
        self.assertIn('direction', self.check('q1', 'With high certainty, seedling size and site preparation help growth.'))

    def test_finding_for_the_wrong_outcome_rejected(self):
        # seedling size was only studied (and found to help) for growth
        self.assertIsNotNone(self.check('q1', 'Seedling size and stock type helps seedling survival.'))
        self.assertIsNone(self.check('q1', 'Seedling size and stock type helps seedling growth.'))

    def test_two_findings_blurred_into_one_rejected(self):
        # fertilization at planting is mixed for survival but increases growth
        self.assertIn('direction', self.check('q1', 'Fertilization at planting shows mixed results for survival and growth.'))
        self.assertIsNone(self.check('q1', 'Fertilization at planting shows mixed results for seedling survival.'))

    def test_combined_treatment_checked_on_its_own(self):
        self.assertIsNone(self.check('q1', 'Fertilization at planting combined with site preparation increases '
                                     'growth (moderate certainty, 1 study).'))
        self.assertIn('certainty', self.check('q1', 'Fertilization at planting combined with site preparation '
                                              'increases growth (high certainty).'))

    def test_gap_cannot_be_given_a_result(self):
        self.assertIsNone(self.check('q1', 'Nursery fertilization has not been studied for seedling survival.'))
        self.assertIn('direction', self.check('q1', 'Nursery fertilization lowers seedling survival.'))

    # PR #88 review: replies that broke the rules but passed
    def test_q2_catching_up_rejected(self):
        for t in ('The studies cannot say how long. Created marshes catch up with natural ones.',
                  'The studies cannot say how long, but created marshes catch up with natural ones over time.',
                  'The studies cannot say how long. Created marshes gradually approach natural ones.',
                  'The studies cannot say how long. Growth lags until marshes mature.'):
            self.assertIn('duration', self.check('q2', t), t)

    def test_q2_must_open_with_cant_say(self):
        t = ('Growth, size and biomass lag natural marshes (high certainty). Species richness and diversity '
             'lag too (moderate certainty). 8 attributes were never compared.')
        self.assertIn("can't say", self.check('q2', t))

    def test_study_count_tied_to_its_item(self):
        self.assertIn('study count', self.check('q1', 'Site preparation gives mixed results for growth '
                                                     '(high certainty, 3 studies).'))
        self.assertIn('study count', self.check('q1', 'Fertilization at planting increases growth '
                                                     '(high certainty, 11 studies).'))
        self.assertIsNone(self.check('q1', 'Fertilization at planting increases growth (high certainty, 7 studies).'))

    def test_works_and_effective_are_directions(self):
        self.assertIn('direction', self.check('q1', 'Fertilization at planting works for seedling survival '
                                                    '(moderate certainty).'))
        self.assertIsNotNone(self.check('q1', 'Fertilization at planting increases growth (high certainty), '
                                              'and it is effective for survival too.'))

    def test_gap_or_advice_wording_rejected(self):
        self.assertIsNotNone(self.check('q1', 'Nursery fertilization has not been shown to work for seedling survival.'))
        self.assertIsNotNone(self.check('q3', 'Livestock grazing management is not worth doing for any outcome.'))
        self.assertIsNotNone(self.check('q3', 'Livestock grazing management has no studies, so managers can skip it.'))
        self.assertIsNotNone(self.check('q1', 'Competing vegetation lowers survival (high certainty), so controlling '
                                              'it is the key step.'))

    def test_trend_not_read_as_comparison(self):
        self.assertIsNotNone(self.check('q2', 'The studies cannot say how long. Community composition and similarity '
                                              'is no different from natural marshes (moderate certainty).'))
        self.assertIsNone(self.check('q2', 'The studies cannot say how long. Community composition and similarity '
                                           'shows no clear change as marshes age (moderate certainty).'))

    def test_cut_off_and_vague_shares_rejected(self):
        self.assertIn('cut off', self.check('q1', 'Seedling size helps growth (high certainty). Site preparation gives mixed'))
        self.assertIsNotNone(llm.validate('A dozen combinations were studied.', ['123']))
        self.assertIsNotNone(llm.validate('Half of the interventions were studied.', ['123']))

    def test_style_symbols_rejected(self):
        self.assertIn('machine-sounding', self.check('q3', 'The graph is densest for seeding.'))
        self.assertIn('machine-sounding', self.check('q2', 'The studies cannot say how long. Growth, size & biomass lag.'))

    def test_every_template_passes(self):
        import summarize
        for qid, q in self.data.questions.items():
            t = summarize.home_template(qid, self.data)
            _, nums, fl = llm.facts(self.data, q)
            self.assertIsNone(llm.validate(t, nums, fl), '%s template: %s' % (qid, t))


class ValidateTests(unittest.TestCase):
    def test_accepts_numbers_from_the_facts(self):
        self.assertIsNone(llm.validate('Only 123 of 384 combinations were studied.', ['123', '384']))

    def test_rejects_an_invented_number(self):
        self.assertIn('number', llm.validate('About 40 combinations were studied.', ['123']))

    def test_rejects_a_duration(self):
        self.assertIn('duration', llm.validate('Marshes catch up after a decade or so of years.', []))

    def test_rejects_vague_timelines(self):
        self.assertIn('duration', llm.validate('Created marshes eventually reach natural levels.', []))
        self.assertIn('duration', llm.validate('Gains are only seen in the long-term.', []))

    def test_rejects_overclaiming_and_advice(self):
        for t in ('Fertilization is proven to help.', 'There is strong evidence for seeding.',
                  'Managers should use mulch.', 'Site preparation will improve growth.'):
            self.assertIn('overclaims', llm.validate(t, []), t)

    def test_rejects_dashes_and_filler(self):
        for t in ('Seeding helps \u2014 sometimes.', 'Seeding helps - sometimes.', 'Notably, seeding helps.',
                  'This highlights a gap.', 'Overall, results are mixed.'):
            self.assertIn('machine-sounding', llm.validate(t, []), t)
        self.assertIsNone(llm.validate('Non-native species were rarely studied.', []))

    def test_rejects_number_words_not_in_facts(self):
        self.assertIn('number', llm.validate('Eleven studies looked at this.', ['3']))
        self.assertIsNone(llm.validate('Eleven studies looked at this.', ['11']))

    def test_rejects_gap_as_negative(self):
        self.assertIn('negative', llm.validate('Grazing is ineffective.', []))

    def test_rejects_empty_markup_long_and_too_many_sentences(self):
        self.assertEqual(llm.validate('  ', []), 'empty')
        self.assertEqual(llm.validate('<b>x</b>', []), 'markup')
        self.assertEqual(llm.validate('**x**', []), 'markup')
        self.assertEqual(llm.validate('a' * 700, []), 'too long')
        self.assertIn('sentences', llm.validate('A. B. C. D.', []))

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
