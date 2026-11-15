import importlib.util
import json
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

STEPS = Path(__file__).resolve().parents[1] / 'backend/services/timetable_parser/steps'
sys.path.insert(0, str(STEPS))
stub = types.ModuleType('read_timetable_cells')
stub.check_ollama = lambda: None
stub.read_with_retries = lambda path: None
stub.MODEL = 'qwen2.5vl:3b'
stub.PROMPT = 'test-prompt'
spec = importlib.util.spec_from_file_location(
    'patched_read_dynamic_cells',
    STEPS / 'read_dynamic_cells.py'
)
module = importlib.util.module_from_spec(spec)

# Install the fake dependency only while loading this test module.
# Restore the original sys.modules entry afterward.
# Replace only this dependency temporarily.
# Do NOT restore the entire sys.modules dictionary: that can unload
# NumPy/OpenCV entries while their native extensions remain initialized.
_MISSING = object()
_original = sys.modules.get('read_timetable_cells', _MISSING)

try:
    sys.modules['read_timetable_cells'] = stub
    spec.loader.exec_module(module)
finally:
    if _original is _MISSING:
        sys.modules.pop('read_timetable_cells', None)
    else:
        sys.modules['read_timetable_cells'] = _original

class PersistentOCRCacheTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            result = {'text': '22CS71', 'uncertain': False, 'reason': ''}
            key = module.persistent_cache_key(b'image-bytes')
            module.write_persistent_cache(path, key, result)
            self.assertEqual(module.read_persistent_cache(path, key), result)

    def test_different_images_have_different_keys(self):
        self.assertNotEqual(module.persistent_cache_key(b'a'), module.persistent_cache_key(b'b'))

    def test_invalid_cache_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            key = module.persistent_cache_key(b'image')
            (Path(directory) / f'{key}.json').write_text('{broken')
            self.assertIsNone(module.read_persistent_cache(Path(directory), key))

    def test_disabled_by_default_in_isolated_reader(self):
        with patch.dict('os.environ', {'NMIT_TIMETABLE_OCR_CACHE_DIR': ''}):
            self.assertIsNone(module.get_persistent_cache_directory())

if __name__ == '__main__':
    unittest.main()
