import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import httpx
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from backend.main import app
from backend.auth_utils import get_current_user

VALID_ROWS = [{
    "class": "P2TEST",
    "day_of_week": "Monday",
    "time_slot": "09:00-09:55",
    "subject_code": "TEST101",
    "is_lab": False,
    "lab_id": None,
}]

PAYLOAD = {
    "rows": VALID_ROWS,
    "department": "CSE",
    "expected_revision": "0" * 32,
    "confirm_replace": True,
    "confirm_subgroup": False,
}


class SaveHttpErrorTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_current_user] = (
            lambda: SimpleNamespace(role="admin", id=998)
        )
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()

    def check_failure(self, error, expected_status):
        fake_db = MagicMock()
        fake_db.rpc.return_value.execute.side_effect = error

        with patch(
            "backend.routes.admin_timetable.get_supabase_client",
            return_value=fake_db,
        ):
            response = self.client.post(
                "/admin/timetable/save",
                json=PAYLOAD,
            )

        self.assertEqual(
            response.status_code,
            expected_status,
            response.text,
        )

    def test_timeout_returns_503(self):
        self.check_failure(
            httpx.ReadTimeout("Timed out"),
            503,
        )

    def test_stale_revision_returns_409(self):
        self.check_failure(
            APIError({
                "code": "40001",
                "message": "Timetable changed since preview",
            }),
            409,
        )

    def test_invalid_lab_returns_422(self):
        self.check_failure(
            APIError({
                "code": "23503",
                "message": "Foreign key violation",
            }),
            422,
        )


if __name__ == "__main__":
    unittest.main()
