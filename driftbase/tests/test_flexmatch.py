
from six.moves import http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch

REGION = "eu-west-1"

class MockGameLiftClient(object):
    def start_matchmaking(self, **kwargs):
        return {
            "MatchmakingTicket": {
                "TicketId": 123,
                "Status": "Searching"
            }
        }

class FlexMatchApiTest(BaseCloudkitTest):
    def test_patch_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'update_player_latency', return_value=None):
            with patch.object(flexmatch, 'get_player_latency_averages', return_value={}):
                self.patch(flexmatch_url, data={'latency_ms': 123, "region": REGION}, expected_status_code=http_client.OK)
                self.patch(flexmatch_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)

    def test_post_api(self):
        self.make_player()
        with patch.object(flexmatch, 'upsert_flexmatch_ticket', return_value={}):
            response = self.post(self.endpoints["flexmatch"], expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_get_api(self):
        self.make_player()
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_update_latency_returns_correct_averages(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6] # We expect unrounded integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            response = self.patch(flexmatch_url, data={'latency_ms': latency, "region": REGION}, expected_status_code=http_client.OK)
            self.assertEqual(response.json()[REGION], expected_avg[i])

    #def test_start_matchmaking_without_a_party_creates_event(self):
    #    self.auth()
    #    flexmatch_url = self.endpoints["flexmatch"]
    #    response = self.post(flexmatch_url)
    #    notification, message_number = self.get_player_notification("matchmaking", "StartedMatchMaking")

