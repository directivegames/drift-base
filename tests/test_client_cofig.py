import http.client as http_client
from unittest.mock import patch
from driftbase.systesthelper import DriftBaseTestCase


class ClientConfigTest(DriftBaseTestCase):
    """
    Tests for the /client_configs endpoint
    """

    @patch('driftbase.api.client_config._get_client_config')
    def test_client_config_get_successful_response(self, mock_get_client_config):
        # Mock the return value of _get_client_config to simulate the configurations
        mock_get_client_config.return_value = {
            "client_config_1": "URL",
            "client_config_2": "1",
            "client_config_3": "",
            "client_config_4": "URL"
        }

        response = self.get("/client_configs", expected_status_code=http_client.OK)

        self.assertEqual(response.status_code, http_client.OK)
        data = response.json()
        expected_output = {
            "client_configs": [
                {"config_name": "client_config_1", "value": "URL"},
                {"config_name": "client_config_2", "value": "1"},
                {"config_name": "client_config_3", "value": ""},
                {"config_name": "client_config_4", "value": "URL"}
            ]
        }
        self.assertEqual(data, expected_output)
