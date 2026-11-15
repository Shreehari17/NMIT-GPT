import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.timetable_parser.local_pipeline import build_admin_payload


class VerticalMappingTests(unittest.TestCase):
    def test_only_geometrically_covered_day_is_filled(self):
        ocr = {
            'complete': True, 'period_count': 2,
            'day_names': ['Monday', 'Tuesday', 'Wednesday'],
            'cells': [
                {'day': 'Monday', 'first_slot': 1, 'last_slot': 1, 'text': '', 'status': 'vertical_merge_review'},
                {'day': 'Tuesday', 'first_slot': 1, 'last_slot': 2, 'text': '22CSG73 LAB', 'status': 'recognized'},
                {'day': 'Wednesday', 'first_slot': 1, 'last_slot': 1, 'text': '', 'status': 'vertical_merge_review'},
            ],
        }
        times = {'all_resolved': True, 'headers': [
            {'slot': 1, 'time_slot': '09:00-09:55'},
            {'slot': 2, 'time_slot': '09:55-10:05'},
        ]}
        klass = {'detected_class': '7A', 'needs_review': False}
        payload = build_admin_payload(ocr, klass, times, vertical=[
            {'slot': 1, 'days': ['Monday'], 'text': 'BREAK', 'uncertain': False},
        ])
        rows = payload['rows']
        monday = next(r for r in rows if r['day_of_week'] == 'Monday')
        wednesday = next(r for r in rows if r['day_of_week'] == 'Wednesday')
        tuesday = [r for r in rows if r['day_of_week'] == 'Tuesday']
        self.assertEqual(monday['activity'], 'BREAK')
        self.assertIn('REVIEW REQUIRED', wednesday['activity'])
        self.assertEqual(len(tuesday), 2)
        self.assertTrue(all(r['subject_code'] == '22CSG73' for r in tuesday))


if __name__ == '__main__':
    unittest.main()
