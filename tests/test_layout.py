import unittest

import layout


class MapRegionTest(unittest.TestCase):
    def test_same_window_keeps_region(self):
        win = {"x": 0, "y": 25, "w": 1700, "h": 1000}
        region = {"x": 87, "y": 129, "w": 1204, "h": 970}
        self.assertEqual(layout.map_region(region, win, win), region)

    def test_move_and_shrink(self):
        old = {"x": 100, "y": 100, "w": 1000, "h": 800}
        new = {"x": 0, "y": 0, "w": 500, "h": 400}
        region = {"x": 200, "y": 300, "w": 600, "h": 400}
        self.assertEqual(layout.map_region(region, old, new), {"x": 50, "y": 100, "w": 300, "h": 200})


class SplitFramesTest(unittest.TestCase):
    def test_panel_and_table_share_the_screen(self):
        panel, table = layout.split_frames({"x": 87, "y": 129, "w": 1204, "h": 970})
        self.assertGreaterEqual(panel["w"], layout.PANEL_MIN_W)
        self.assertLessEqual(panel["w"], layout.PANEL_MAX_W)
        self.assertEqual(table["x"] + table["w"], panel["x"])
        self.assertEqual(table["h"], panel["h"])


if __name__ == "__main__":
    unittest.main()
