import unittest

import cards


class NormalizeTest(unittest.TestCase):
    def test_variants_of_ten_of_hearts(self):
        for raw in ("T♥", "10h", "Th", "th", "10♥", " T h ", "10H"):
            self.assertEqual(cards.normalize_card(raw), "Th", raw)

    def test_face_cards_and_suits(self):
        self.assertEqual(cards.normalize_card("K♠"), "Ks")
        self.assertEqual(cards.normalize_card("a♦"), "Ad")
        self.assertEqual(cards.normalize_card("7c"), "7c")

    def test_garbage_is_none(self):
        for raw in ("", None, "?", "1h", "Kx", "KK", "11s"):
            self.assertIsNone(cards.normalize_card(raw), raw)

    def test_list_from_string_or_list(self):
        self.assertEqual(cards.normalize_cards("T♥ K♥"), ["Th", "Kh"])
        self.assertEqual(cards.normalize_cards(["10h", "Kh"]), ["Th", "Kh"])
        self.assertEqual(cards.normalize_cards(None), [])
        self.assertEqual(cards.normalize_cards("-"), [])


class ValidDealTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(cards.valid_deal(["Ah", "Kh"], []))
        self.assertTrue(cards.valid_deal(["Ah", "Kh"], ["2c", "3d", "4s"]))

    def test_duplicate_card_is_invalid(self):
        self.assertFalse(cards.valid_deal(["Ah", "Kh"], ["Ah", "3d", "4s"]))

    def test_wrong_counts_are_invalid(self):
        self.assertFalse(cards.valid_deal(["Ah"], []))
        self.assertFalse(cards.valid_deal(["Ah", "Kh"], ["2c", "3d"]))


class HandClassTest(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(cards.hand_class(["Kh", "Ah"]), "AKs")
        self.assertEqual(cards.hand_class(["Kd", "Ah"]), "AKo")
        self.assertEqual(cards.hand_class(["Td", "Th"]), "TT")

    def test_pretty(self):
        self.assertEqual(cards.pretty("Th"), "T♥")
        self.assertEqual(cards.pretty_list(["As", "Kd"]), "A♠ K♦")


if __name__ == "__main__":
    unittest.main()
