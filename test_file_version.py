import math
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from filter_review import format_review_results

from finger_lens_core import (
    FILTER_NAMES,
    FILTER_SETS,
    crossed_polygon_mask,
    draw_zones,
    fashion_filter,
    is_l_gesture,
    subtle_white_polyline,
    thumb_index_only,
)
from finger_lens_file import (
    ACTIVE_FILTER_IDS,
    apply_video_orientation,
    DEFAULT_FIVE_SUITES,
    DEFAULT_TWO_FILTER_SEQUENCE,
    FILTER_CN_NAMES,
    FILTER_ID_BY_OPTION,
    FILTER_OPTIONS,
    filters_for_time,
    preview_png_data,
    reorder_items,
    reorder_suites,
    scroll_units,
    video_metadata,
)


def l_hand() -> np.ndarray:
    points = np.zeros((21, 2), dtype=np.float32)
    points[0] = (0, 100)
    points[1:5] = [(-8, 82), (-18, 66), (-34, 61), (-52, 60)]
    points[5:9] = [(0, 66), (0, 43), (0, 21), (0, 0)]
    points[9:13] = [(15, 66), (18, 46), (15, 57), (12, 64)]
    points[13:17] = [(28, 70), (31, 52), (27, 61), (24, 69)]
    points[17:21] = [(40, 76), (43, 61), (39, 69), (36, 76)]
    return points


def rotate(points: np.ndarray, degrees: float) -> np.ndarray:
    radians = math.radians(degrees)
    matrix = np.array(
        [[math.cos(radians), -math.sin(radians)], [math.sin(radians), math.cos(radians)]],
        dtype=np.float32,
    )
    return points @ matrix.T


class FileVersionTests(unittest.TestCase):
    def test_filter_review_result_lists_keep_drop_and_pending(self):
        result = format_review_results({50: "keep", 51: "drop", 60: "keep"})
        self.assertIn("保留（2 个）", result)
        self.assertIn("50  纯蓝剪影", result)
        self.assertIn("60  红蓝电影", result)
        self.assertIn("不要（1 个）", result)
        self.assertIn("51  红色罩染", result)
        self.assertIn("未决定（8 个）", result)

    def test_new_stylized_portrait_filters_are_static_and_shape_preserving(self):
        frame = np.random.default_rng(21).integers(0, 256, (90, 120, 3), dtype=np.uint8)
        for style in range(51, 61):
            first = fashion_filter(frame, 0.0, style)
            later = fashion_filter(frame, 9.0, style)
            self.assertEqual(first.shape, frame.shape)
            self.assertEqual(first.dtype, np.uint8)
            np.testing.assert_array_equal(first, later)
            difference = float(np.mean(np.abs(first.astype(np.int16) - frame.astype(np.int16))))
            self.assertGreater(difference, 8.0, style)
            self.assertLess(difference, 115.0, style)

    def test_cobalt_silhouette_uses_only_blue_and_black(self):
        gradient = np.tile(np.arange(0, 256, dtype=np.uint8), (80, 1))
        frame = cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR)
        result = fashion_filter(frame, 0.0, 50)
        colors = {tuple(color) for color in result.reshape(-1, 3)}
        self.assertEqual(colors, {(0, 0, 0), (255, 0, 12)})

    def test_eleventh_set_is_solid_green(self):
        self.assertEqual(FILTER_SETS[11], (41, 41, 41, 41))
        self.assertEqual(FILTER_NAMES[41], "CHROMA GREEN")
        frame = np.random.default_rng(2).integers(0, 256, (40, 60, 3), dtype=np.uint8)
        result = fashion_filter(frame, 0.0, 41)
        np.testing.assert_array_equal(result, np.full_like(frame, (0, 255, 0)))

    def test_l_gesture_is_rotation_invariant(self):
        hand = l_hand()
        for degrees in (0, 90, 180, 270, -45):
            self.assertTrue(is_l_gesture(rotate(hand, degrees)), degrees)

    def test_open_hand_is_not_l_gesture(self):
        hand = l_hand()
        for finger, x in zip(((9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)), (15, 28, 40)):
            for offset, landmark in enumerate(finger):
                hand[landmark] = (x, 66 - offset * 22)
        self.assertFalse(is_l_gesture(hand))

    def test_both_hands_required_for_thumb_index_only(self):
        hand = l_hand()
        self.assertTrue(thumb_index_only({"Left": hand, "Right": hand + (160, 0)}))
        self.assertFalse(thumb_index_only({"Left": hand}))

    def test_reviewed_filter_selection_is_applied_to_defaults(self):
        expected = {7, 8, 11, 12, 13, 15, 18, 19, 22, 25, 26, 27, 29, 33, 34, 38, 39, 41, 42, 43, 44, 45, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59}
        self.assertEqual(set(ACTIVE_FILTER_IDS), expected)
        self.assertEqual(DEFAULT_TWO_FILTER_SEQUENCE, ())
        self.assertTrue(all(filter_id in expected for suite in DEFAULT_FIVE_SUITES for filter_id in suite))
        self.assertEqual(set(filter_id for suite in DEFAULT_FIVE_SUITES for filter_id in suite), expected)
        self.assertEqual(DEFAULT_FIVE_SUITES[-1], (41, 41, 41, 41))
        old_ids = set(range(1, 50))
        new_ids = set(range(50, 60))
        for suite in DEFAULT_FIVE_SUITES[:8]:
            self.assertTrue(set(suite) & old_ids)
            self.assertTrue(set(suite) & new_ids)
        self.assertTrue({2, 4, 28, 30, 60}.isdisjoint(ACTIVE_FILTER_IDS))

    def test_filter_options_show_names_without_internal_id_prefixes(self):
        self.assertEqual(len(FILTER_OPTIONS), len(ACTIVE_FILTER_IDS))
        self.assertEqual(len(set(FILTER_OPTIONS)), len(FILTER_OPTIONS))
        for filter_id, option in zip(ACTIVE_FILTER_IDS, FILTER_OPTIONS):
            self.assertEqual(option, FILTER_CN_NAMES[filter_id])
            self.assertEqual(FILTER_ID_BY_OPTION[option], filter_id)
            self.assertFalse(option.startswith(f"{filter_id:02d}"))

    def test_kept_negative_filters_are_dynamic_and_split_across_suites(self):
        negative_ids = (42, 43, 44, 45)
        suite_indexes = []
        frame = np.random.default_rng(8).integers(0, 256, (72, 96, 3), dtype=np.uint8)
        for style in negative_ids:
            first = fashion_filter(frame, 0.1, style)
            later = fashion_filter(frame, 0.9, style)
            self.assertEqual(first.shape, frame.shape)
            self.assertEqual(first.dtype, np.uint8)
            self.assertGreater(np.mean(np.abs(first.astype(int) - later.astype(int))), 0.5, style)
            matches = [index for index, suite in enumerate(DEFAULT_FIVE_SUITES) if style in suite]
            self.assertEqual(len(matches), 1)
            suite_indexes.append(matches[0])
        self.assertEqual(len(set(suite_indexes)), 4)
        self.assertTrue({46, 47, 48, 49}.isdisjoint(ACTIVE_FILTER_IDS))

    def test_preview_uses_tk_compatible_png(self):
        frame = np.full((24, 32, 3), (10, 80, 160), dtype=np.uint8)
        import base64

        decoded = base64.b64decode(preview_png_data(frame))
        self.assertTrue(decoded.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_crossed_mask_keeps_bow_tie_shape(self):
        points = np.array([[10, 10], [10, 50], [50, 10], [50, 50]], dtype=np.float32)
        mask = crossed_polygon_mask((64, 64), points)
        self.assertGreater(mask[30, 15], 0)
        self.assertGreater(mask[30, 45], 0)
        self.assertGreater(mask[30, 30], 0)
        self.assertEqual(mask[10, 30], 0)

    def test_zone_boundary_is_thin_translucent_white(self):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        points = np.array([[10, 10], [10, 50], [50, 50], [50, 10]], dtype=np.float32)
        subtle_white_polyline(frame, points)
        colored = frame[np.any(frame > 0, axis=2)]
        self.assertGreater(len(colored), 0)
        np.testing.assert_array_equal(colored[:, 0], colored[:, 1])
        np.testing.assert_array_equal(colored[:, 1], colored[:, 2])
        self.assertLessEqual(int(colored.max()), 110)
        # OpenCV anti-aliasing may add two very faint neighboring pixels, while
        # the actual stroke remains one pixel wide.
        self.assertLessEqual(int(np.count_nonzero(np.any(frame > 0, axis=2)[30, 7:14])), 3)

    def test_green_screen_zone_is_fully_opaque(self):
        frame = np.random.default_rng(32).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        left = np.zeros((21, 2), dtype=np.float32)
        right = np.zeros((21, 2), dtype=np.float32)
        left[4], left[8] = (10, 10), (10, 50)
        right[8], right[4] = (50, 10), (50, 50)
        output = draw_zones(
            frame,
            {"Left": left, "Right": right},
            phase=9.5,
            style=1,
            finger_mode="two",
            custom_filter_ids=(41,),
        )
        quad = np.array([left[4], left[8], right[8], right[4]], dtype=np.float32)
        mask = crossed_polygon_mask(frame.shape[:2], quad)
        expected = frame.copy()
        expected[mask > 0] = (0, 255, 0)
        subtle_white_polyline(expected, quad)
        np.testing.assert_array_equal(output, expected)

    def test_complete_suites_can_be_drag_reordered(self):
        suites = [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12)]
        self.assertEqual(reorder_suites(suites, 0, 2), [suites[1], suites[2], suites[0]])
        self.assertEqual(reorder_suites(suites, 2, 0), [suites[2], suites[0], suites[1]])
        self.assertEqual(reorder_items([42, 44, 25], 2, 0), [25, 42, 44])

    def test_two_finger_custom_sequence_speed_and_wraparound(self):
        suites = ((1, 2, 3, 4), (5, 6, 7, 8))
        sequence = (42, 51, 41)
        for elapsed in (0.0, 1.0, 99.0, 3600.0):
            self.assertEqual(filters_for_time("two", sequence, suites, None, elapsed), ((42,), 0))
            self.assertEqual(filters_for_time("two", (41,), suites, None, elapsed), ((41,), 0))
        self.assertEqual(filters_for_time("two", sequence, suites, 1.0, 0.0), ((42,), 0))
        self.assertEqual(filters_for_time("two", sequence, suites, 1.0, 1.0), ((51,), 1))
        self.assertEqual(filters_for_time("two", sequence, suites, 1.0, 2.0), ((41,), 2))
        self.assertEqual(filters_for_time("two", sequence, suites, 1.0, 3.0), ((42,), 0))
        with self.assertRaises(ValueError):
            filters_for_time("two", (), suites, 1.0, 0.0)
        with self.assertRaises(ValueError):
            filters_for_time("two", (46,), suites, 1.0, 0.0)

    def test_trackpad_and_mousewheel_scrolling(self):
        self.assertEqual(scroll_units(1), -1)
        self.assertEqual(scroll_units(-1), 1)
        self.assertEqual(scroll_units(120), -1)
        self.assertEqual(scroll_units(-240), 2)
        self.assertEqual(scroll_units(button_number=4), -1)
        self.assertEqual(scroll_units(button_number=5), 1)

    def test_five_finger_time_switch_and_never_switch(self):
        suites = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12))
        self.assertEqual(filters_for_time("five", (1,), suites, 2.0, 1.99), (suites[0], 0))
        self.assertEqual(filters_for_time("five", (1,), suites, 2.0, 2.0), (suites[1], 1))
        self.assertEqual(filters_for_time("five", (1,), suites, 2.0, 6.0), (suites[0], 0))
        self.assertEqual(filters_for_time("five", (1,), suites, None, 99.0), (suites[0], 0))

    def test_video_metadata_reads_common_avi(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 12.0, (64, 48))
            self.assertTrue(writer.isOpened())
            for value in (20, 80, 140):
                writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
            writer.release()
            width, height, fps, frames, preview = video_metadata(path)
            self.assertEqual((width, height), (64, 48))
            self.assertAlmostEqual(fps, 12.0, places=1)
            self.assertGreaterEqual(frames, 3)
            self.assertEqual(preview.shape, (48, 64, 3))

    def test_manual_video_orientation_fallback(self):
        frame = np.zeros((30, 50, 3), dtype=np.uint8)
        frame[:10, :15] = (3, 40, 220)
        clockwise = apply_video_orientation(frame, 90)
        upside_down = apply_video_orientation(frame, 180)
        counterclockwise = apply_video_orientation(frame, 270)
        self.assertEqual(clockwise.shape, (50, 30, 3))
        self.assertEqual(upside_down.shape, frame.shape)
        self.assertEqual(counterclockwise.shape, (50, 30, 3))
        np.testing.assert_array_equal(clockwise, cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE))
        np.testing.assert_array_equal(upside_down, cv2.rotate(frame, cv2.ROTATE_180))
        np.testing.assert_array_equal(counterclockwise, cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE))
        self.assertIs(apply_video_orientation(frame, 0), frame)


if __name__ == "__main__":
    unittest.main()
