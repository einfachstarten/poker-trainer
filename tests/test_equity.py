import random
import unittest

import equity


class EquityTest(unittest.TestCase):
    def test_aces_heads_up_preflop(self):
        e = equity.equity(["As", "Ah"], [], opponents=1, iterations=6000, rng=random.Random(1))
        self.assertAlmostEqual(e, 0.85, delta=0.03)

    def test_more_opponents_lower_equity(self):
        rng = random.Random(2)
        one = equity.equity(["Kh", "Th"], [], opponents=1, iterations=4000, rng=rng)
        four = equity.equity(["Kh", "Th"], [], opponents=4, iterations=4000, rng=rng)
        self.assertGreater(one, four)
        self.assertLess(four, 0.40)

    def test_made_nuts_on_river(self):
        e = equity.equity(["As", "Ks"], ["Qs", "Js", "Ts", "2d", "3c"], opponents=2,
                          iterations=500, rng=random.Random(3))
        self.assertEqual(e, 1.0)

    def test_invalid_cards_give_none(self):
        self.assertIsNone(equity.equity(["As"], [], opponents=1))
        self.assertIsNone(equity.equity(["As", "As"], [], opponents=1))


class PotOddsTest(unittest.TestCase):
    def test_required_equity(self):
        self.assertAlmostEqual(equity.required_equity(pot=120, to_call=40), 0.25)

    def test_free_check_needs_nothing(self):
        self.assertEqual(equity.required_equity(pot=120, to_call=0), 0.0)

    def test_unknown_pot(self):
        self.assertIsNone(equity.required_equity(pot=None, to_call=40))


class PreflopRankTest(unittest.TestCase):
    def test_percentiles_are_ordered(self):
        self.assertLess(equity.preflop_percentile("AA"), 0.01)
        self.assertLess(equity.preflop_percentile("AKs"), 0.06)
        self.assertGreater(equity.preflop_percentile("72o"), 0.95)
        self.assertLess(equity.preflop_percentile("AKs"), equity.preflop_percentile("KTs"))

    def test_all_169_hands_ranked(self):
        self.assertEqual(len(equity.PREFLOP_ORDER), 169)
        self.assertEqual(len(set(equity.PREFLOP_ORDER)), 169)


if __name__ == "__main__":
    unittest.main()
