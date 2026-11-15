"""Offline timetable time regression tests. No Supabase or model calls."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    for package in ("RAG_ENGINE", "RAG_ENGINE.src"):
        module = types.ModuleType(package)
        module.__path__ = [str(ROOT / package.replace('.', '/'))]
        sys.modules.setdefault(package, module)
    db = types.ModuleType("RAG_ENGINE.src.db")
    db.get_supabase_client = Mock()
    sys.modules[db.__name__] = db
    from RAG_ENGINE.src import sql_queries, timetable_slots
    return db, sql_queries, timetable_slots


class FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def select(self, *_): return self
    def eq(self, col, val):
        self.calls.append(('eq', col, val))
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self
    def in_(self, col, vals):
        self.calls.append(('in', col, list(vals)))
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self
    def execute(self): return types.SimpleNamespace(data=self.rows)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db, cls.queries, cls.slots = load()

    def setUp(self):
        # Other tests may have imported sql_queries before our DB stub.
        # Patch the actual function used by the query under test.
        self.db.get_supabase_client.reset_mock()
        getter_patch = patch.object(
            self.queries,
            "get_supabase_client",
            self.db.get_supabase_client,
        )
        getter_patch.start()
        self.addCleanup(getter_patch.stop)

    def test_aliases(self):
        f = self.slots
        self.assertEqual(f.canonical_slot('01:30-02:25'), '13:30-14:25')
        self.assertEqual(f.slot_variants('13:30-14:25'), ['13:30-14:25', '01:30-02:25'])
        self.assertEqual(f.teaching_period('15:20-16:15'), '7')
        self.assertEqual(f.teaching_period('11:55-12:35'), '?')
        self.assertLess(f.slot_sort_key('12:35-01:30'), f.slot_sort_key('13:30-14:25'))

    def test_period_mapping(self):
        self.assertEqual(self.queries.resolve_time_slot('5'), '13:30-14:25')
        self.assertEqual(self.queries.resolve_time_slot('2:30pm'), '14:25-15:20')

    def test_full_day_order(self):
        fake = Mock()
        fake.table.side_effect = lambda table: FakeTable([
            {'class':'6A','day_of_week':'Monday','time_slot':'15:20-16:15','subject_code':None},
            {'class':'6A','day_of_week':'Monday','time_slot':'12:35-01:30','subject_code':None},
            {'class':'6A','day_of_week':'Monday','time_slot':'09:00-09:55','subject_code':None},
        ])
        self.db.get_supabase_client.return_value = fake
        rows = self.queries.query_full_day_timetable('6A','Monday')
        self.assertEqual([r['time_slot'] for r in rows], ['09:00-09:55','12:35-01:30','15:20-16:15'])

    def test_free_period_occupied_in_24h(self):
        fake = Mock()
        fake.table.side_effect = lambda table: FakeTable([
            {'class':'6A','day_of_week':'Monday','time_slot':'13:30-14:25'},
        ])
        self.db.get_supabase_client.return_value = fake
        free = self.queries.query_free_periods('6A','Monday')
        self.assertNotIn('5', [item['period'] for item in free])

    def test_new_old_period_rows_both_found(self):
        calls = []
        db_rows = [
            {'class':'6A','day_of_week':'Monday','time_slot':'13:30-14:25','subject_code':None},
            {'class':'6B','day_of_week':'Monday','time_slot':'01:30-02:25','subject_code':None},
        ]
        fake = Mock()
        def table(name):
            assert name == 'timetable', f'Unexpected table {name}'
            t = FakeTable(list(db_rows))
            calls.append(t)
            return t
        fake.table.side_effect = table
        self.db.get_supabase_client.return_value = fake
        result = self.queries.query_class_at_period('Monday', '5')
        self.assertEqual(len(result), 2)
        self.assertIn(('in', 'time_slot', ['13:30-14:25','01:30-02:25']), calls[0].calls)


if __name__ == '__main__': unittest.main()
