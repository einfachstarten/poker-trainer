import unittest

from speech_text import MarkerStream, parse_markers, speakable


class MarkerStreamTest(unittest.TestCase):
    def feed(self, chunks):
        s = MarkerStream()
        out = []
        for c in chunks:
            out.extend(s.feed(c))
        out.extend(s.flush())
        return out

    def test_sentences_are_split(self):
        out = self.feed(["Call. Du brauchst 25 Pro", "zent und hast 38. Passt"])
        self.assertEqual([x for k, x in out if k == "sentence"],
                         ["Call.", "Du brauchst 25 Prozent und hast 38.", "Passt"])

    def test_marker_split_across_chunks_is_not_spoken(self):
        out = self.feed(["[[EMPFEH", "LUNG CALL 40]]\nCall, die Odds passen."])
        self.assertEqual(out[0], ("marker", "EMPFEHLUNG CALL 40"))
        self.assertEqual([x for k, x in out if k == "sentence"], ["Call, die Odds passen."])

    def test_decimal_numbers_do_not_split(self):
        out = self.feed(["Raise auf 2,5 Big Blinds. Fertig."])
        self.assertEqual([x for k, x in out if k == "sentence"], ["Raise auf 2,5 Big Blinds.", "Fertig."])


class ParseMarkersTest(unittest.TestCase):
    def test_recommendation(self):
        self.assertEqual(parse_markers(["EMPFEHLUNG RAISE 60"])["recommendation"], ("RAISE", 60.0))
        self.assertEqual(parse_markers(["EMPFEHLUNG CHECK -"])["recommendation"], ("CHECK", None))
        self.assertEqual(parse_markers(["EMPFEHLUNG ALL-IN"])["recommendation"], ("ALL-IN", None))

    def test_strategy_change(self):
        m = parse_markers(["STRATEGIE aggression=2 bluff=1"])
        self.assertEqual(m["strategy"], {"aggression": 2, "bluff": 1})

    def test_unknown_marker_is_ignored(self):
        self.assertEqual(parse_markers(["QUATSCH 1"]), {})


class SpeakableTest(unittest.TestCase):
    def test_symbols_and_pronunciation(self):
        t = speakable("K♥ T♥ → Raise", {"Raise": "Räis"})
        self.assertNotIn("♥", t)
        self.assertNotIn("→", t)
        self.assertIn("Räis", t)

    def test_percent(self):
        self.assertIn("Prozent", speakable("54 % Equity", {}))


if __name__ == "__main__":
    unittest.main()
