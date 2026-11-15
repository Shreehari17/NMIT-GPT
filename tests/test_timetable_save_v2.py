import unittest
from pathlib import Path
from backend.services.timetable_save_validation import (
    validate_save_rows, validate_department, is_subgroup,
)

ROOT = Path(__file__).resolve().parents[1]


def row(**changes):
    out = {
        'class': '6A', 'day_of_week': 'Monday', 'time_slot': '10:05-11:00',
        'subject_code': '22CSL68', 'activity': 'A1-L3 / A2-L4 / A3-L10',
        'is_lab': True, 'lab_id': None,
    }
    out.update(changes)
    return out


class TimetableV2Tests(unittest.TestCase):
    def test_department_required(self):
        self.assertEqual(validate_department(' CSE '), 'CSE')
        for value in (None, '', '   ', 'X' * 51):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_department(value)

    def test_descriptive_lab_string_never_fk(self):
        with self.assertRaisesRegex(ValueError, 'lab_id must'):
            validate_save_rows([row(lab_id='A1-L3/ A2-L4/ A3-L10')])

    def test_known_style_lab_id_passes_syntax(self):
        cls, rows = validate_save_rows([row(lab_id='LAB3')])
        self.assertEqual(cls, '6A')
        self.assertEqual(rows[0]['lab_id'], 'LAB3')

    def test_main_class_is_not_subgroup(self):
        self.assertFalse(is_subgroup('6A'))
        self.assertFalse(is_subgroup('7A'))
        self.assertTrue(is_subgroup('6A-A1'))
        self.assertTrue(is_subgroup('6A-A2'))

    def test_main_class_rows_not_silently_expanded(self):
        _, rows = validate_save_rows([row()])
        self.assertEqual([r['class'] for r in rows], ['6A'])

    def test_mixed_class_and_subgroup_rejected(self):
        with self.assertRaises(ValueError):
            validate_save_rows([row(), row(**{'class':'6A-A1', 'time_slot':'11:00-11:55'})])

    def test_sql_scopes_exact_class_and_preserves_department(self):
        sql = (ROOT / 'database/atomic_timetable_replace_v2.sql').read_text()
        self.assertIn('DELETE FROM public.timetable WHERE "class" = p_class', sql)
        self.assertIn('"Dept"', sql)
        self.assertIn('p_expected_revision', sql)
        self.assertIn('pg_advisory_xact_lock', sql)
        self.assertIn('REVOKE ALL', sql)

    def test_frontend_sends_revision_and_department(self):
        html = (ROOT / 'frontend/admin.html').read_text()
        self.assertIn('expected_revision: existing.revision', html)
        self.assertIn('confirm_subgroup: !!existing.is_subgroup', html)
        self.assertIn('department,', html)


if __name__ == '__main__':
    unittest.main()
