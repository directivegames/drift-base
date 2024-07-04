import http
import http.client as http_client
from unittest.mock import patch

from drift.test_helpers.systesthelper import setup_tenant, remove_tenant, uuid_string
from driftbase.systesthelper import DriftBaseTestCase
from driftbase.utils.test_utils import BaseCloudkitTest


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class ClientConfigTest(DriftBaseTestCase):
    """
    Tests for the /client_config endpoint
    """

    @patch('driftbase.api.client_config._get_client_config')
    def test_client_config_get(self, mock_get_client_config):
        # Mock the return value of _get_client_config
        mock_get_client_config.return_value = {
            "feature_1": "enabled",
            "feature_2": "disabled"
        }

        self.auth()
        response = self.get("/client_config", expected_status_code=http.client.OK)

        self.assertEqual(response.status_code, http_client.OK)
        data = response.json()
        expected_output = {
            "client_configs": [
                {"config_name": "feature_1", "value": "enabled"},
                {"config_name": "feature_2", "value": "disabled"}
            ]
        }
        self.assertEqual(data, expected_output)
