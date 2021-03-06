from mock import patch, MagicMock
from six.moves import http_client

from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase
from drift.utils import get_config


def setUpModule():
    setup_tenant()

    conf = get_config()

    conf.table_store.get_table('platforms').add({
        'product_name': conf.product['product_name'],
        'provider_name': 'oculus',
        "provider_details": {
            "access_token": "four",
            "sekrit": "five"
        }})

    conf.table_store.get_table('platforms').add({
        'product_name': conf.product['product_name'],
        'provider_name': 'steam',
        "provider_details": {
            "appid": 12345,
            "key": "steam key"
        }})


def tearDownModule():
    remove_tenant()


class AuthTests(DriftBaseTestCase):

    def test_oculus_authentication(self):
        # Oculus provisional authentication check
        data = {
            "provider": "oculus",
            "provider_details": {
                "provisional": True, "username": "someuser", "password": "somepass"
            }
        }
        with patch('driftbase.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            self.post('/auth', data=data)

        # verify error with empty username
        data['provider_details']['username'] = ""
        self.post('/auth', data=data, expected_status_code=http_client.UNAUTHORIZED)

        # Oculus normal authentication check
        nonce = "140000003DED3A"
        data = {
            "provider": "oculus",
            "provider_details": {
                "nonce": nonce,
                "user_id": "testuser"
            }
        }
        with patch('driftbase.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            self.post('/auth', data=data)

    def test_steam_authentication(self):
        # Steam normal authentication check
        data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": 12345,
                "steam_id": "steamdude"
            }
        }
        with patch('driftbase.auth.steam._call_authenticate_user_ticket') as mock_auth:
            mock_auth.return_value.status_code = 200
            mock_auth.return_value.json = MagicMock()
            mock_auth.return_value.json.return_value = {'response': {'params': {'steamid': u'steamtester'}}}
            with patch('driftbase.auth.steam._call_check_app_ownership') as mock_own:
                mock_own.return_value.status_code = 200
                self.post('/auth', data=data)
