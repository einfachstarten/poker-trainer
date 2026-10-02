import time
import unittest
from unittest import mock

import numpy as np
from PIL import Image

import watcher


def frame(table=0, buttons=0):
    """A 100x100 picture: upper 80 rows are the table, lower 20 the button strip."""
    a = np.zeros((100, 100, 3), dtype=np.uint8)
    a[:80] = table
    a[80:] = buttons
    return Image.fromarray(a)


class WatcherTest(unittest.TestCase):
    def run_watcher(self, frames, seconds, **kw):
        """Feed one frame per capture, repeating the last one."""
        seq = list(frames)
        seen = []

        def capture_region(region):
            return seq.pop(0) if len(seq) > 1 else seq[0]

        with mock.patch.object(watcher.capture, "capture_region_pil", capture_region):
            w = watcher.Watcher(lambda: {}, lambda img, reason: seen.append(reason),
                                interval=0.02, settle=0.06, max_wait=0.5, buttons_zone=0.2, **kw)
            w.start()
            time.sleep(seconds)
            w.stop()
            time.sleep(0.05)
        return seen, w

    def test_first_frame_is_read_once_and_a_still_table_stays_quiet(self):
        seen, _ = self.run_watcher([frame()], 0.5, turn_gap=0.05, table_gap=0.05)
        self.assertEqual(seen, ["buttons"])

    def test_buttons_appearing_trigger_a_read(self):
        seen, _ = self.run_watcher([frame()] * 8 + [frame(buttons=200)], 0.6, turn_gap=0.05, table_gap=5)
        self.assertEqual(seen, ["buttons", "buttons"])

    def test_table_changes_are_rate_limited(self):
        frames = [frame()] * 8 + [frame(table=120)] * 8 + [frame(table=240)]
        seen, _ = self.run_watcher(frames, 0.8, turn_gap=0.05, table_gap=5)
        self.assertEqual(seen, ["buttons"])  # table-only changes wait for the long gap

    def test_table_change_is_read_when_the_gap_allows(self):
        seen, _ = self.run_watcher([frame()] * 8 + [frame(table=120)], 0.6, turn_gap=0.05, table_gap=0.05)
        self.assertEqual(seen, ["buttons", "table"])

    def test_restless_picture_is_read_after_max_wait(self):
        flicker = [frame(table=40 * (i % 2)) for i in range(200)]
        seen, _ = self.run_watcher(flicker, 1.5, turn_gap=0.05, table_gap=0.05)
        self.assertGreaterEqual(len(seen), 2)

    def test_force_reads_immediately(self):
        seen = []
        with mock.patch.object(watcher.capture, "capture_region_pil", lambda region: frame()):
            w = watcher.Watcher(lambda: {}, lambda img, reason: seen.append(reason),
                                interval=5, turn_gap=60, table_gap=60)
            w.start()
            time.sleep(0.1)
            w.force()
            time.sleep(0.2)
            w.stop()
        self.assertEqual(seen, ["forced"])

    def test_failing_callback_does_not_kill_the_loop(self):
        calls = []

        def boom(img, reason):
            calls.append(reason)
            raise RuntimeError("kaputt")

        with mock.patch.object(watcher.capture, "capture_region_pil", lambda region: frame()):
            w = watcher.Watcher(lambda: {}, boom, interval=0.02, settle=0.02)
            w.start()
            time.sleep(0.2)
            w.force()
            time.sleep(0.2)
            w.stop()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
