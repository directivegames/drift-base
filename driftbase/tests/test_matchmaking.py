
from six.moves import http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch

import boto3
import random
import sys

REGION = "eu-west-1"

class TestMatchmakingAPI(BaseCloudkitTest):
    def test_patch_api(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'update_player_latency', return_value=None):
            with patch.object(flexmatch, 'get_player_latency_averages', return_value={}):
                self.patch(matchmaking_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
                self.patch(matchmaking_url, data={'latency_ms': 123, "region": REGION}, expected_status_code=http_client.OK)

    def test_post_api(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'upsert_flexmatch_ticket', return_value={}):
            self.post(matchmaking_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
            response = self.post(matchmaking_url, data={"matchmaker": "test"}, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_get_api(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(matchmaking_url, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

class FlexMatchTest(BaseCloudkitTest):
    def test_update_latency_returns_correct_averages(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6] # We expect unrounded integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            response = self.patch(matchmaking_url, data={'latency_ms': latency, "region": REGION}, expected_status_code=http_client.OK)
            self.assertEqual(response.json()[REGION], expected_avg[i])

    def test_start_matchmaking(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(boto3, 'client', MockGameLiftClient):
            response = self.post(matchmaking_url, data={"matchmaker": "test"}, expected_status_code=http_client.OK).json()
            self.assertTrue(response["status"] == "QUEUED")
            self.assertEqual(response["ticket_id"], 123)

    def test_start_matchmaking_doesnt_modify_ticket_if_same_player_reissues_request(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(boto3, 'client', MockGameLiftClient):
            response1 = self.post(matchmaking_url, data={"matchmaker": "test"}, expected_status_code=http_client.OK).json()
            first_id = response1["debug_id"]
            response2 = self.post(matchmaking_url, data={"matchmaker": "test"}, expected_status_code=http_client.OK).json()
            second_id = response2["debug_id"]
            self.assertEqual(first_id, second_id)

    def test_start_matchmaking_creates_event(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(boto3, 'client', MockGameLiftClient):
            self.post(matchmaking_url, data={"matchmaker": "test"}, expected_status_code=http_client.OK).json()
            notification, message_number = self.get_player_notification("matchmaking", "StartedMatchMaking")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "StartedMatchMaking")

    def test_matchmaking_includes_party_members(self):
        # Create a party of 2
        member_name = self.make_player()
        member_id = self.player_id
        host_name = self.make_player()
        host_id = self.player_id
        invite = self.post(self.endpoints["party_invites"], data={'player_id': member_id}, expected_status_code=http_client.CREATED).json()
        # Accept the invite
        self.auth(username=member_name)
        notification, message_number = self.get_player_notification("party_notification", "invite")
        self.patch(notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.OK).json()
        # Let member start matchmaking, host should be included in the ticket
        with patch.object(boto3, 'client', MockGameLiftClient):
            response = self.post(self.endpoints["matchmaking"], data={"matchmaker": "test"}, expected_status_code=http_client.OK).json()
            players = response["Players"]
            self.assertEqual(len(players), 2)
            expected_players = {host_id, member_id}
            response_players = {int(e["PlayerId"]) for e in players}
            self.assertSetEqual(response_players, expected_players)

    def test_start_matchmaking_creates_event_for_party_members(self):
        # Create a party of 2
        member_name = self.make_player()
        member_id = self.player_id
        host_name = self.make_player()
        host_id = self.player_id
        invite = self.post(self.endpoints["party_invites"], data={'player_id': member_id},
                           expected_status_code=http_client.CREATED).json()
        # Accept the invite
        self.auth(username=member_name)
        notification, message_number = self.get_player_notification("party_notification", "invite")
        self.patch(notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.OK).json()
        # Let member start matchmaking, host should be included in the ticket
        with patch.object(boto3, 'client', MockGameLiftClient):
            response = self.post(self.endpoints["matchmaking"], data={"matchmaker": "test"},
                                 expected_status_code=http_client.OK).json()
        # Check if party host got the message
        self.auth(host_name)
        notification, message_number = self.get_player_notification("matchmaking", "StartedMatchMaking")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "StartedMatchMaking")

class MockGameLiftClient(object):
    def __init__(self, *args, **kwargs):
        pass

    def start_matchmaking(self, **kwargs):
        return {
            "MatchmakingTicket": {
                "ticket_id": 123,
                # MEMO TO SELF: the current processor re-uses the status field in redis for ticket events later, so we never actually see the status, just the latest mm event
                "status": "QUEUED", # Docs say the ticket will always be created with status QUEUED;
                "Players": kwargs["Players"],
                "debug_id": random.randint(-sys.maxsize, sys.maxsize)
            }
        }
    # For quick reference: https://docs.aws.amazon.com/gamelift/latest/apireference/API_StartMatchmaking.html
    ResponseSyntax = """
    {
        "MatchmakingTicket": {
            "ConfigurationArn": "string",
            "ConfigurationName": "string",
            "EndTime": number,
            "EstimatedWaitTime": number,
            "GameSessionConnectionInfo": {
                "DnsName": "string",
                "GameSessionArn": "string",
                "IpAddress": "string",
                "MatchedPlayerSessions": [
                    {
                        "PlayerId": "string",
                        "PlayerSessionId": "string"
                    }
                ],
                "Port": number
            },
            "Players": [
                {
                    "LatencyInMs": {
                        "string": number
                    },
                    "PlayerAttributes": {
                        "string": {
                            "N": number,
                            "S": "string",
                            "SDM": {
                                "string": number
                            },
                            "SL": ["string"]
                        }
                    },
                    "PlayerId": "string",
                    "Team": "string"
                }
            ],
            "StartTime": number,
            "Status": "string",
            "StatusMessage": "string",
            "StatusReason": "string",
            "TicketId": "string"
        }
    }
    """