import unittest

import strategy
from strategy import Recommendation, Situation, StrategyProfile


def sit(**kw):
    base = dict(street="flop", hand_class="AKs", equity=0.5, pot=100, to_call=0,
                hero_stack=1000, opponents=1, position=None)
    base.update(kw)
    return Situation(**base)


class ProfileTest(unittest.TestCase):
    def test_default_is_moderate(self):
        p = StrategyProfile()
        self.assertEqual((p.tightness, p.aggression, p.bluff), (2, 3, 2))
        self.assertEqual(p.name, "Moderat aggressiv")

    def test_roundtrip_and_clamping_of_values(self):
        p = StrategyProfile.from_dict({"tightness": 9, "aggression": 0, "bluff": "3"})
        self.assertEqual((p.tightness, p.aggression, p.bluff), (5, 1, 3))
        self.assertEqual(StrategyProfile.from_dict(p.to_dict()), p)

    def test_legacy_style_maps_to_preset(self):
        self.assertEqual(StrategyProfile.from_legacy("LAG").aggression, 5)
        self.assertEqual(StrategyProfile.from_legacy("unknown"), StrategyProfile())

    def test_more_aggression_lowers_value_threshold(self):
        calm = StrategyProfile(aggression=1).thresholds(opponents=1)
        wild = StrategyProfile(aggression=5).thresholds(opponents=1)
        self.assertGreater(calm["value_bet"], wild["value_bet"])

    def test_looser_profile_plays_more_hands(self):
        self.assertLess(StrategyProfile(tightness=1).thresholds(1)["open_range"],
                        StrategyProfile(tightness=5).thresholds(1)["open_range"])

    def test_thresholds_scale_with_opponents(self):
        p = StrategyProfile()
        self.assertGreater(p.thresholds(1)["value_bet"], p.thresholds(4)["value_bet"])


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.p = StrategyProfile()

    def test_trash_preflop_folds_to_a_bet(self):
        r = self.p.baseline(sit(street="preflop", hand_class="72o", equity=0.33, pot=15, to_call=10))
        self.assertEqual(r.action, "FOLD")

    def test_trash_preflop_checks_when_free(self):
        r = self.p.baseline(sit(street="preflop", hand_class="72o", equity=0.33, pot=20, to_call=0))
        self.assertEqual(r.action, "CHECK")

    def test_premium_preflop_raises(self):
        r = self.p.baseline(sit(street="preflop", hand_class="AA", equity=0.85, pot=15, to_call=10))
        self.assertEqual(r.action, "RAISE")

    def test_kts_preflop_is_not_reraised_into_a_big_bet(self):
        # der Fall aus der History: K♥T♥ wurde dreimal hochgeraist
        r = self.p.baseline(sit(street="preflop", hand_class="KTs", equity=0.6, pot=130, to_call=75))
        self.assertIn(r.action, ("FOLD", "CALL"))

    def test_weak_hand_checks_when_free(self):
        r = self.p.baseline(sit(equity=0.30, to_call=0))
        self.assertEqual(r.action, "CHECK")

    def test_strong_hand_bets_for_value(self):
        r = self.p.baseline(sit(equity=0.85, to_call=0, pot=100))
        self.assertEqual(r.action, "RAISE")
        self.assertGreater(r.amount, 0)
        self.assertLessEqual(r.amount, 100)

    def test_call_when_odds_fit(self):
        r = self.p.baseline(sit(equity=0.40, pot=160, to_call=40))
        self.assertEqual(r.action, "CALL")
        self.assertEqual(r.amount, 40)

    def test_fold_when_odds_do_not_fit(self):
        r = self.p.baseline(sit(equity=0.20, pot=100, to_call=80))
        self.assertEqual(r.action, "FOLD")

    def test_unknown_equity_gives_no_action(self):
        r = self.p.baseline(sit(equity=None))
        self.assertEqual(r.action, "?")


class ClampTest(unittest.TestCase):
    def setUp(self):
        self.p = StrategyProfile()

    def test_raise_below_threshold_is_capped(self):
        s = sit(equity=0.40, pot=160, to_call=40)
        r = self.p.clamp(Recommendation("RAISE", 200), s)
        self.assertEqual(r.action, "CALL")
        self.assertTrue(r.clamped)

    def test_allowed_raise_passes(self):
        s = sit(equity=0.88, pot=100, to_call=0)
        r = self.p.clamp(Recommendation("RAISE", 60), s)
        self.assertEqual((r.action, r.amount, r.clamped), ("RAISE", 60, False))

    def test_oversized_bet_is_cut_down(self):
        s = sit(equity=0.88, pot=100, to_call=0)
        r = self.p.clamp(Recommendation("RAISE", 900), s)
        self.assertEqual(r.action, "RAISE")
        self.assertLess(r.amount, 900)
        self.assertTrue(r.clamped)

    def test_all_in_below_threshold_becomes_raise_or_less(self):
        s = sit(equity=0.70, pot=100, to_call=0, hero_stack=5000)
        r = self.p.clamp(Recommendation("ALL-IN", None), s)
        self.assertNotEqual(r.action, "ALL-IN")
        self.assertTrue(r.clamped)

    def test_fold_is_never_recommended_when_check_is_free(self):
        r = self.p.clamp(Recommendation("FOLD", None), sit(equity=0.1, to_call=0))
        self.assertEqual(r.action, "CHECK")

    def test_aggressive_profile_allows_what_moderate_caps(self):
        s = sit(equity=0.60, pot=100, to_call=0)
        self.assertTrue(self.p.clamp(Recommendation("RAISE", 50), s).clamped)
        self.assertFalse(StrategyProfile(aggression=5).clamp(Recommendation("RAISE", 50), s).clamped)

    def test_plan_for_a_strong_hand_while_waiting(self):
        text = self.p.plan(sit(equity=0.85, pot=100, to_call=0))
        self.assertIn("Bet 60", text)
        self.assertIn("mitgehen", text)

    def test_plan_for_a_weak_hand_while_waiting(self):
        text = self.p.plan(sit(equity=0.10, pot=100, to_call=0))
        self.assertIn("Check", text)
        self.assertIn("aussteigen", text)
        self.assertNotIn("mitgehen bis", text)

    def test_plan_names_the_price_worth_paying(self):
        # 40 % equity minus 6 points reserve = 34 % → up to pot * 0.34 / 0.66
        text = self.p.plan(sit(equity=0.40, pot=100, to_call=0))
        self.assertIn("mitgehen bis etwa 52", text)

    def test_plan_preflop(self):
        self.assertIn("Erhöhen", self.p.plan(sit(street="preflop", hand_class="AA", equity=0.85)))
        self.assertIn("aussteigen", self.p.plan(sit(street="preflop", hand_class="72o", equity=0.3)).lower())

    def test_plan_without_cards_is_empty(self):
        self.assertEqual(self.p.plan(sit(equity=None, hand_class=None)), "")

    def test_describe_mentions_numbers(self):
        text = self.p.describe(sit(equity=0.4, pot=160, to_call=40))
        self.assertIn("Moderat aggressiv", text)
        self.assertIn("%", text)


if __name__ == "__main__":
    unittest.main()
