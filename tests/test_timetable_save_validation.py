import unittest
from backend.services.timetable_save_validation import validate_save_rows


def row(**kwargs):
    base = {'class': '7A', 'day_of_week': 'Monday', 'time_slot': '09:00-09:55',
            'subject_code': '22CS71', 'activity': None, 'is_lab': False, 'lab_id': None}
    base.update(kwargs)
    return base


class SaveValidationTests(unittest.TestCase):
    def test_valid(self):
        cls, rows = validate_save_rows([row()])
        self.assertEqual(cls, '7A')
        self.assertEqual(rows[0]['time_slot'], '09:00-09:55')

    def test_reject_duplicate_slot_even_if_different_activity(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_save_rows([row(), row(activity='Different')])

    def test_reject_review_placeholder(self):
        with self.assertRaisesRegex(ValueError, 'REVIEW REQUIRED'):
            validate_save_rows([row(activity='[REVIEW REQUIRED: unreadable merged cell]')])

    def test_reject_invalid_slot(self):
        with self.assertRaisesRegex(ValueError, 'invalid'):
            validate_save_rows([row(time_slot='15:20-15:10')])

    def test_reject_mixed_class(self):
        with self.assertRaisesRegex(ValueError, 'one class'):
            validate_save_rows([row(), row(**{'class':'6A', 'time_slot':'10:05-11:00'})])

    def test_reject_overlaps(self):
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            validate_save_rows([row(), row(time_slot='09:30-10:00')])

    def test_lab_fk_not_fabricated(self):
        _, rows = validate_save_rows([row(is_lab=True, lab_id=None)])
        self.assertIsNone(rows[0]['lab_id'])

    def test_reject_blank(self):
        with self.assertRaisesRegex(ValueError, 'required'):
            validate_save_rows([row(subject_code=None, activity=None)])

if __name__ == '__main__':
    unittest.main()
