
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

class FlexMatchTest(BaseCloudkitTest):
        
    def test_patch_latency(self):
        self.auth()
        flexmatch_url = self.endpoints["flexmatch"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6] # We expect unrounded integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            response = self.patch(flexmatch_url, data={'latency_ms': latency, "region": "eu-west-1" }, expected_status_code=http_client.OK)
            reported_avg = response.json()["latency_avg"]["eu-west-1"]
            self.assertEqual(reported_avg, expected_avg[i])

    def test_start_matchmaking_without_a_party_creates_event(self):
        self.auth()
        flexmatch_url = self.endpoints["flexmatch"]
        response = self.post(flexmatch_url)
        notification, message_number = self.get_player_notification("matchmaking", "StartedMatchMaking")

