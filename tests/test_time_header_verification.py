"""Fast isolated time-header verification tests, no Ollama required."""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
# Step scripts run as standalone executables; expose their sibling imports here.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/services/timetable_parser/steps"))
from tempfile import TemporaryDirectory
from PIL import Image
from backend.services.timetable_parser.steps.auto_headers import (
    suspicious_final, reread_suspicious_final,
)


class TimeHeaderVerificationTests(unittest.TestCase):
    def setUp(self):
        self.headers = [
            {'slot': i, 'time_slot': t}
            for i, t in enumerate((
                '09:00-09:55', '09:55-10:05', '10:05-11:00',
                '11:00-11:55', '11:55-12:35', '12:35-13:30',
                '13:30-14:25', '14:25-15:20', '15:20-15:45',
            ), 1)
        ]
        self.raw = [
            {'slot': x['slot'], 'raw': x['time_slot'], 'needs_review': False}
            for x in self.headers
        ]

    def test_detect_suspicious_short_end(self):
        self.assertTrue(suspicious_final(self.headers))
        self.headers[-1]['time_slot'] = '15:20-16:15'
        self.assertFalse(suspicious_final(self.headers))

    def test_two_agreeing_rereads_fix_without_hardcoding(self):
        with TemporaryDirectory() as d:
            with patch('backend.services.timetable_parser.steps.auto_headers.recognize_header',
                       side_effect=[{'raw': '3:20-4:15', 'uncertain': False}]*2):
                fixed = reread_suspicious_final(Image.new('RGB', (1100, 110)),
                                                 [i*100 for i in range(11)],
                                                 {'top': 0, 'bottom': 95},
                                                 self.raw, Path(d))
            self.assertEqual(fixed[-1]['time_slot'], '15:20-16:15')

    def test_disagreement_fails_closed(self):
        with TemporaryDirectory() as d:
            with patch('backend.services.timetable_parser.steps.auto_headers.recognize_header',
                       side_effect=[{'raw':'3:20-4:15','uncertain':False},
                                    {'raw':'3:20-3:45','uncertain':False}]):
                with self.assertRaisesRegex(ValueError, 'disagree'):
                    reread_suspicious_final(Image.new('RGB', (1100, 110)),
                                            [i*100 for i in range(11)],
                                            {'top': 0, 'bottom': 95},
                                            self.raw, Path(d))


if __name__ == '__main__':
    unittest.main()
