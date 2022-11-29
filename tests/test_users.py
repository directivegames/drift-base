import http.client as http_client

from drift.systesthelper import big_number
from driftbase.systesthelper import DriftBaseTestCase
from tests import has_key


class UsersTest(DriftBaseTestCase):
    """
    Tests for the /users endpoint
    """

    def test_users(self):
        self.auth()
        resp = self.get("/")
        my_user_id = resp.json()["current_user"]["user_id"]

        resp = self.get("/users")
        self.assertTrue(isinstance(resp.json(), list))

        resp = self.get("/users/%s" % my_user_id)
        self.assertTrue(isinstance(resp.json(), dict))
        self.assertNotIn("identities", resp.json())

        self.assertFalse(has_key(resp.json(), "password_hash"))

    def test_non_existing_user_not_found(self):
        self.auth()
        self.get("/users/{}".format(big_number), expected_status_code=http_client.NOT_FOUND)

    def test_requires_authentication(self):
        r = self.get("/users", expected_status_code=http_client.UNAUTHORIZED).json()
        self.assertIn("error", r)
        self.assertIn("code", r["error"])
        self.assertIn("Authorization Required", r["error"]["description"])
