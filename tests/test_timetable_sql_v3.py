"""Offline guardrails. Database behavior requires staging_rollback_smoke_test.sql."""
from pathlib import Path
import unittest

SQL = (Path(__file__).resolve().parents[1] / 'database' / 'atomic_timetable_replace_v3.sql').read_text()


class SqlV3Checks(unittest.TestCase):
    def test_rpc_contract_unchanged(self):
        self.assertIn('CREATE OR REPLACE FUNCTION public.replace_class_timetable_v2(', SQL)
        self.assertIn('p_class text, p_rows jsonb, p_department text, p_expected_revision text', SQL)

    def test_not_security_definer(self):
        self.assertEqual(SQL.count('\nSECURITY INVOKER\n'), 2)
        self.assertNotIn('SECURITY DEFINER', SQL)

    def test_role_restrictions(self):
        self.assertIn('FROM PUBLIC, anon, authenticated', SQL)
        self.assertIn('TO service_role', SQL)

    def test_interval_overlap_guard(self):
        self.assertIn('v_start < v_prev_end', SQL)
        self.assertIn('v_end <= v_start', SQL)

    def test_exact_class_scope(self):
        self.assertIn('DELETE FROM public.timetable WHERE "class" = p_class', SQL)
        self.assertNotIn('LIKE p_class', SQL)

    def test_revision_checked_under_lock(self):
        self.assertLess(SQL.index('pg_advisory_xact_lock('), SQL.index('v_revision IS DISTINCT FROM p_expected_revision'))

    def test_input_checks(self):
        for token in ('jsonb_typeof(p_rows)', 'Invalid weekday or 24-hour time slot',
                      'REVIEW[[:space:]]+REQUIRED', 'LAB[1-9][0-9]*'):
            self.assertIn(token, SQL)


if __name__ == '__main__':
    unittest.main()
