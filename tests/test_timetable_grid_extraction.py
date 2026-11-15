import io
import json
import unittest
from unittest.mock import patch
from PIL import Image
from backend.routes.timetable_grid_extraction import bbox, extract_grid_first, parse_json
from backend.routes.timetable_validation import validate_extracted_rows


class GridTests(unittest.TestCase):
    def test_coordinates_reject_invalid_boxes(self):
        self.assertEqual(bbox([100, 100, 500, 500], (1000, 1000)), (100, 100, 500, 500))
        for bad in ([10, 10, 10, 200], [-1, 0, 500, 500], [100, 100, 1001, 900], "none"):
            with self.assertRaises(ValueError):
                bbox(bad, (1000, 1000))

    def test_parse_json_fence(self):
        self.assertEqual(parse_json('```json\n{"rows": []}\n```'), {"rows": []})
        with self.assertRaises(ValueError):
            parse_json('[]')

    def test_day_crops_and_disallows_cross_day_leaks(self):
        # A synthetic page and mocked Gemini; no API requests and no hardcoded timetable.
        layout = {"class_label": "VII(A)", "grid_bbox": [50, 80, 950, 700],
                  "header_bbox": [50, 80, 950, 140], "day_bboxes": {
                      "Monday": [50, 145, 950, 210], "Tuesday": [50, 220, 950, 285]},
                  "legend_bbox": [50, 730, 950, 950], "warnings": []}
        responses = [layout,
                     {"rows": [{"class": "VII(A)", "day_of_week": "Monday", "time_slot": "09:00-09:55", "subject_code": "22CS71", "activity": "HPC", "is_lab": False, "lab_id": None}], "warnings": []},
                     {"rows": [{"class": "VII(A)", "day_of_week": "Monday", "time_slot": "10:05-11:00", "subject_code": "22CS74", "activity": "Cloud", "is_lab": False, "lab_id": None}], "warnings": []}]
        image = Image.new('RGB', (1000, 1000), 'white')
        with patch('backend.routes.timetable_grid_extraction.render_pages', return_value=[image]), patch('backend.routes.timetable_grid_extraction.provider_json', side_effect=responses):
            result = extract_grid_first(None, 'mock', b'PDF', 'application/pdf')
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['day_of_week'], 'Monday')
        self.assertTrue(any('different day' in w for w in result['warnings']))

    def test_lunch_repetition_is_flagged(self):
        template = {"class": "7A", "day_of_week": "Monday", "subject_code": None, "activity": "LUNCH", "is_lab": False, "lab_id": None}
        rows, warnings = validate_extracted_rows([{**template, "time_slot": "11:55-12:35"}, {**template, "time_slot": "12:35-13:30"}])
        self.assertEqual(len(rows), 2)
        self.assertTrue(any('LUNCH appears in 2 slots' in w for w in warnings))

    def test_break_conflict_is_flagged(self):
        common = {"class": "7A", "day_of_week": "Tuesday", "time_slot": "09:55-10:05", "subject_code": None, "lab_id": None}
        _, warnings = validate_extracted_rows([{**common, "activity": "BREAK", "is_lab": False}, {**common, "activity": "Lab", "is_lab": True}])
        self.assertTrue(any('conflicts' in w for w in warnings))

if __name__ == '__main__':
    unittest.main()
