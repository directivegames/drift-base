import http.client as http_client

from drift.systesthelper import big_number
from driftbase.systesthelper import DriftBaseTestCase
from driftbase.tests import has_key
from drift.utils import get_config
from mock import patch, MagicMock


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
        r = self.get("/users", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("error", r.json())
        self.assertIn("code", r.json()["error"])
        self.assertIn("Authorization Required", r.json()["error"]["description"])


class SteamUsersTest(DriftBaseTestCase):
    """
    Tests for the /users/steam/ endpoint
    """
    app_id = 12345
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        conf = get_config()
        conf.table_store.get_table('platforms').add({
            'product_name': conf.product['product_name'],
            'provider_name': 'steam',
            "provider_details": {
                "appid": cls.app_id,
                "key": "steam key"
            }})

    @classmethod
    def tearDownClass(cls):
        conf = get_config()
        conf.table_store.get_table('platforms').remove({
            'product_name': conf.product['product_name'],
            'provider_name': 'steam',
            "provider_details": {
                "appid": cls.app_id,
                "key": "steam key"
            }})
        super().tearDownClass()

    def test_get_user_by_steam_id(self):
        steam_id = 1234567890
        user_data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": self.app_id,
                "steamid": str(steam_id)
            }
        }
        # Setup steam user
        with patch('driftbase.auth.steam._call_authenticate_user_ticket') as mocked_auth:
            mocked_auth.return_value.status_code = 200
            mocked_auth.return_value.json = MagicMock()
            mocked_auth.return_value.json.return_value = {'response': {'params': {'steamid': str(steam_id)}}}
            with patch('driftbase.auth.steam._call_check_app_ownership') as mocked_own:
                mocked_own.return_value.status_code = 200
                self.post('/auth', data=user_data)
        # Test for success
        with self.as_bearer_token_user("service"):
            self.get(f"/users/steam/{steam_id+123}", expected_status_code=http_client.NOT_FOUND)
            r = self.get(f"/users/steam/{steam_id}", expected_status_code=http_client.OK).json()
            self.assertIn("create_date", r)
            self.assertIn("players", r)
            self.assertEqual(len(r["players"]), 1)
            player_info = r["players"][0]
            self.assertIn("player_name", player_info)
            self.assertIn("player_id", player_info)
        # Should not be accessible by non-service users
        self.get(f"/users/steam/{steam_id}", expected_status_code=http_client.UNAUTHORIZED)
        self.auth()
        self.get(f"/users/steam/{steam_id}", expected_status_code=http_client.UNAUTHORIZED)
