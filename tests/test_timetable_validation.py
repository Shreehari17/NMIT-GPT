import unittest
from backend.routes.timetable_validation import validate_extracted_rows, time_slot


class ValidationTests(unittest.TestCase):
    def test_time_normalization(self):
        self.assertEqual(time_slot("9:00 – 9:55"), "09:00-09:55")
        self.assertEqual(time_slot("12:35-01:30"), "12:35-13:30")  # normalize afternoon
        self.assertEqual(time_slot("01:30-02:25"), "13:30-14:25")
        self.assertEqual(time_slot("02:25-03:20"), "14:25-15:20")
        self.assertEqual(time_slot("03:20-04:15"), "15:20-16:15")
        self.assertIsNone(time_slot("3:20:4:15"))
        self.assertIsNone(time_slot("25:70-26:00"))

    def test_valid_row_and_empty_nullable_fields(self):
        rows, warnings = validate_extracted_rows([{
            "class": "6A", "day_of_week": "monday", "time_slot": "9:00-9:55",
            "subject_code": None, "activity": "Library", "is_lab": "false", "lab_id": None,
        }])
        self.assertFalse(warnings)
        self.assertEqual(rows[0]["day_of_week"], "Monday")
        self.assertEqual(rows[0]["time_slot"], "09:00-09:55")
        self.assertIsNone(rows[0]["subject_code"])
        self.assertIsNone(rows[0]["lab_id"])

    def test_missing_or_invalid_fields_warn_but_remain_reviewable(self):
        rows, warnings = validate_extracted_rows([{
            "class": None, "day_of_week": "Blursday", "time_slot": "3:20:4:15",
            "subject_code": "22CS71", "activity": None,
        }])
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(len(warnings), 2)

    def test_dedupe_exact_entries_but_keep_parallel_different_subjects(self):
        base = {"class": "6A", "day_of_week": "Tuesday", "time_slot": "09:00-09:55", "subject_code": "CS1"}
        rows, warnings = validate_extracted_rows([base, dict(base), {**base, "subject_code": "CS2"}])
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_empty_and_malformed(self):
        self.assertEqual(validate_extracted_rows([])[0], [])
        with self.assertRaises(ValueError):
            validate_extracted_rows({"foo": "bar"})

    def test_vertical_break_letter_warns(self):
        _, warnings = validate_extracted_rows([{
            "class": "6A", "day_of_week": "Monday", "time_slot": "09:55-10:05", "activity": "B"
        }])
        self.assertTrue(any("BREAK" in w for w in warnings))

if __name__ == "__main__":
    unittest.main()
