
from six.moves import http_client
from driftbase.utils.test_utils import BaseCloudkitTest

class FlexMatchTest(BaseCloudkitTest):
        
    def test_patch_latency(self):
        self.auth()
        flexmatch_url = self.endpoints["flexmatch"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0]
        expected_avg = [1.0, 1.5, 2.0, 3.0, 4.0]
        for i, latency in enumerate(latencies):
            response = self.patch(flexmatch_url, data={'latency_ms': latency}, expected_status_code=http_client.OK)
            reported_avg = response.json()["latency_avg"]
            self.assertEqual(reported_avg, expected_avg[i])

    def test_start_matchmaking_without_a_party(self):
        self.auth()
        flexmatch_url = self.endpoints["flexmatch"]
        breakpoint()
        response = self.post(flexmatch_url)