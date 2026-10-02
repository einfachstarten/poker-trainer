import unittest

from table_state import HandTracker, TableState

READING = {
    "hero_cards": ["5♣", "6s"], "board": ["7s", "Qh", "7c"], "street": "preflop",
    "pot": "$10", "to_call": 0, "hero_stack": "$2,762", "hero_to_act": True,
    "buttons": ["Fold", "Check", "Raise"], "hero_dealer": False,
    "players": [
        {"name": "Tilly", "stack": 554, "in_hand": True, "last_action": None, "dealer": False},
        {"name": "Tyler", "stack": "$30", "in_hand": True, "last_action": None, "dealer": True},
        {"name": "Kristen", "stack": 593, "in_hand": True, "last_action": "Check", "dealer": False},
        {"name": "Gone", "stack": 100, "in_hand": False, "last_action": "Fold", "dealer": False},
    ],
}


def reading(**kw):
    d = dict(READING)
    d.update(kw)
    return d


class TableStateTest(unittest.TestCase):
    def test_normalizes_cards_numbers_and_street(self):
        s = TableState.from_reading(READING)
        self.assertEqual(s.hero_cards, ["5c", "6s"])
        self.assertEqual(s.street, "flop")  # aus dem Board abgeleitet, nicht geglaubt
        self.assertEqual(s.pot, 10)
        self.assertEqual(s.hero_stack, 2762)
        self.assertEqual(s.opponents, 3)
        self.assertTrue(s.valid)

    def test_duplicate_cards_make_state_invalid(self):
        s = TableState.from_reading(reading(board=["5c", "Qh", "7c"]))
        self.assertFalse(s.valid)

    def test_no_cards_is_valid_but_not_actionable(self):
        s = TableState.from_reading(reading(hero_cards=None, hero_to_act=False))
        self.assertTrue(s.valid)
        self.assertFalse(s.actionable)

    def test_position_only_from_dealer_button(self):
        self.assertIsNone(TableState.from_reading(READING).hero_position)
        self.assertEqual(TableState.from_reading(reading(hero_dealer=True)).hero_position, "BTN")

    def test_garbage_reading(self):
        self.assertIsNone(TableState.from_reading("kein json"))
        self.assertIsNone(TableState.from_reading(None))

    def test_opponents_is_at_least_one_when_acting(self):
        s = TableState.from_reading(reading(players=[]))
        self.assertEqual(s.opponents, 1)


class HandTrackerTest(unittest.TestCase):
    def test_new_hand_when_hole_cards_change(self):
        t = HandTracker()
        self.assertIn("new_hand", t.update(TableState.from_reading(READING)))
        self.assertNotIn("new_hand", t.update(TableState.from_reading(reading(board=["7s", "Qh", "7c", "2d"]))))
        self.assertIn("new_hand", t.update(TableState.from_reading(reading(hero_cards=["Ah", "Kd"], board=[]))))
        self.assertEqual(t.hand_no, 2)

    def test_cards_disappearing_does_not_start_a_hand(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        ev = t.update(TableState.from_reading(reading(hero_cards=None, hero_to_act=False)))
        self.assertNotIn("new_hand", ev)
        self.assertEqual(t.hand_no, 1)

    def test_street_and_hero_turn_events(self):
        t = HandTracker()
        ev = t.update(TableState.from_reading(reading(board=[], hero_to_act=False)))
        self.assertNotIn("hero_turn", ev)
        ev = t.update(TableState.from_reading(reading(board=["7s", "Qh", "7c"])))
        self.assertIn("street", ev)
        self.assertIn("hero_turn", ev)

    def test_opponent_actions_counted_once_per_street(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        t.update(TableState.from_reading(READING))
        self.assertEqual(t.opponents["Kristen"]["check"], 1)
        self.assertEqual(t.opponents["Kristen"]["hands"], 1)

    def test_manual_reset(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        t.reset_hand()
        self.assertIn("new_hand", t.update(TableState.from_reading(READING)))

    def test_summary_is_text(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        self.assertIn("Flop", t.summary())

    def test_opponent_label_needs_data(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        self.assertEqual(t.opponent_label("Kristen"), "zu wenig Daten")

    def test_quick_reading_without_players_keeps_the_known_table(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        quick = reading(players=None, opponents_in_hand=2, pot=40)
        state = TableState.from_reading(quick)
        self.assertEqual(state.opponents, 2)
        t.update(state)
        self.assertEqual([o["name"] for o in t.opponents_view()], ["Tilly", "Tyler", "Kristen", "Gone"])


class NewsTest(unittest.TestCase):
    """Plain-language lines about what just happened, for a player who is new to poker."""

    def test_new_hand_street_and_turn(self):
        t = HandTracker()
        t.update(TableState.from_reading(reading(board=[], hero_to_act=False, players=[])))
        self.assertEqual(t.pop_news(), ["Neue Hand. Du hast 5♣ 6♠."])
        t.update(TableState.from_reading(reading(players=[])))
        self.assertEqual(t.pop_news(), ["Flop: 7♠ Q♥ 7♣", "Du bist dran. Check ist gratis."])
        self.assertEqual(t.pop_news(), [])

    def test_turn_with_a_bet_to_call(self):
        t = HandTracker()
        t.update(TableState.from_reading(reading(to_call=150, pot=450, players=[])))
        self.assertIn("Du bist dran. Mitgehen kostet 150.", t.pop_news())

    def test_opponent_actions_once(self):
        t = HandTracker()
        t.update(TableState.from_reading(READING))
        news = t.pop_news()
        self.assertIn("Kristen checkt.", news)
        self.assertIn("Gone steigt aus.", news)
        t.update(TableState.from_reading(READING))
        self.assertEqual(t.pop_news(), [])

    def test_own_action_is_reported(self):
        t = HandTracker()
        t.update(TableState.from_reading(reading(pot=120, to_call=40, hero_stack=1000, players=[])))
        t.pop_news()
        t.update(TableState.from_reading(reading(pot=160, to_call=0, hero_stack=960, hero_to_act=False, players=[])))
        self.assertEqual(t.pop_news(), ["Du gehst mit."])


class HandRecordTest(unittest.TestCase):
    """What a finished hand looked like, for the debrief."""

    def play(self):
        t = HandTracker()
        t.update(TableState.from_reading(reading(board=[], pot=30, to_call=20, hero_stack=1000, players=[])))
        t.note("Empfehlung: CALL 20")
        t.update(TableState.from_reading(reading(board=["7s", "Qh", "7c"], pot=60, to_call=0,
                                                 hero_stack=980, hero_to_act=False, players=[])))
        t.update(TableState.from_reading(reading(board=["7s", "Qh", "7c"], pot=60, to_call=0, hero_stack=980,
                                                 hero_to_act=False, players=[], winner="Tilly",
                                                 showdown=[{"name": "Tilly", "cards": ["Qs", "Qd"]}])))
        return t

    def test_nothing_finished_while_the_hand_runs(self):
        self.assertIsNone(self.play().pop_finished_hand())

    def test_record_when_the_next_hand_starts(self):
        t = self.play()
        t.update(TableState.from_reading(reading(hero_cards=["Ah", "Kd"], board=[], hero_stack=980,
                                                 hero_to_act=False, players=[])))
        rec = t.pop_finished_hand()
        self.assertEqual(rec["hand_no"], 1)
        self.assertEqual(rec["cards"], ["5c", "6s"])
        self.assertEqual(rec["board"], ["7s", "Qh", "7c"])
        self.assertEqual(rec["delta"], -20)
        self.assertEqual(rec["winner"], "Tilly")
        self.assertEqual(rec["showdown"], [{"name": "Tilly", "cards": ["Qs", "Qd"]}])
        for line in ("Neue Hand. Du hast 5♣ 6♠.", "Empfehlung: CALL 20", "Du gehst mit.",
                     "Flop: 7♠ Q♥ 7♣", "Tilly zeigt Q♠ Q♦.", "Tilly gewinnt den Pot."):
            self.assertIn(line, rec["log"])
        self.assertLess(rec["log"].index("Empfehlung: CALL 20"), rec["log"].index("Du gehst mit."))
        self.assertIsNone(t.pop_finished_hand())
        self.assertEqual(t.hand_log, ["Neue Hand. Du hast A♥ K♦."])

    def test_hero_winning_is_named_as_such(self):
        t = HandTracker()
        t.update(TableState.from_reading(reading(players=[], winner="You")))
        self.assertIn("Du gewinnst den Pot.", t.pop_news())


class HeroActionTest(unittest.TestCase):
    def turn(self, **kw):
        t = HandTracker()
        base = dict(board=["7s", "Qh", "7c"], pot=120, to_call=40, hero_stack=1000, hero_to_act=True)
        base.update(kw)
        t.update(TableState.from_reading(reading(**base)))
        return t

    def test_call(self):
        t = self.turn()
        t.update(TableState.from_reading(reading(pot=160, to_call=0, hero_stack=960, hero_to_act=False)))
        self.assertEqual(t.pop_hero_action(), "CALL")
        self.assertIsNone(t.pop_hero_action())

    def test_raise(self):
        t = self.turn()
        t.update(TableState.from_reading(reading(pot=280, to_call=0, hero_stack=840, hero_to_act=False)))
        self.assertEqual(t.pop_hero_action(), "RAISE")

    def test_fold(self):
        t = self.turn()
        t.update(TableState.from_reading(reading(hero_cards=None, pot=120, hero_stack=1000, hero_to_act=False)))
        self.assertEqual(t.pop_hero_action(), "FOLD")

    def test_check(self):
        t = self.turn(to_call=0)
        t.update(TableState.from_reading(reading(pot=120, to_call=0, hero_stack=1000, hero_to_act=False)))
        self.assertEqual(t.pop_hero_action(), "CHECK")

    def test_same_decision_still_open(self):
        t = self.turn()
        t.update(TableState.from_reading(reading(pot=121, to_call=40, hero_stack=1000, hero_to_act=True)))
        self.assertIsNone(t.pop_hero_action())


if __name__ == "__main__":
    unittest.main()
