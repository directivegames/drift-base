
from six.moves import http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch
import uuid

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
            response = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_get_api(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(matchmaking_url, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_delete_api(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'cancel_player_ticket', return_value={}):
            self.delete(matchmaking_url, expected_status_code=http_client.NO_CONTENT)


class FlexMatchTest(BaseCloudkitTest):
    # NOTE TO SELF:  The idea behind splitting the api tests from this class was to be able to test the flexmatch
    # module functions separately from the rest endpoints.  I've got a mocked application context with a fake redis
    # setup stashed away, allowing code like
    # with _mocked_redis(self):
    #    for i, latency in enumerate(latencies):
    #        flexmatch.update_player_latency(self.player_id, "best-region", latency)
    #        average_by_region = flexmatch.get_player_latency_averages(self.player_id)
    # but I keep it stashed away until I can spend time digging into RedisCache in drift as it extends some redis
    # operations which conflict with the fake redis setup I made.
    def test_update_latency_returns_correct_averages(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6]  # We expect integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            response = self.patch(matchmaking_url, data={'latency_ms': latency, "region": REGION}, expected_status_code=http_client.OK)
            self.assertEqual(response.json()[REGION], expected_avg[i])

    def test_start_matchmaking(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            self.assertTrue(response["Status"] == "QUEUED")

    def test_start_matchmaking_doesnt_modify_ticket_if_same_player_reissues_request(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response1 = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            first_id = response1["TicketId"]
            response2 = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            second_id = response2["TicketId"]
            self.assertEqual(first_id, second_id)

    def test_start_matchmaking_creates_event(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
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
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(self.endpoints["matchmaking"], data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
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
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(self.endpoints["matchmaking"], data={"matchmaker": "unittest"},
                                 expected_status_code=http_client.OK).json()
        # Check if party host got the message
        self.auth(host_name)
        notification, message_number = self.get_player_notification("matchmaking", "StartedMatchMaking")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "StartedMatchMaking")

    def test_delete_ticket(self):
        self.make_player()
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            # delete without a ticket, expect NOT_FOUND
            self.delete(matchmaking_url, expected_status_code=http_client.NOT_FOUND)
            # start the matchmaking and then stop it.  Expect OK back
            response = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            self.assertTrue(response["Status"] == "QUEUED")
            # Check that we have a stored ticket
            response = self.get(matchmaking_url, expected_status_code=http_client.OK)
            self.assertIn("TicketId", response.json())
            self.delete(matchmaking_url, expected_status_code=http_client.NO_CONTENT)
            # Check that the ticket is indeed gone
            response = self.get(matchmaking_url, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_party_member_can_delete_ticket(self):
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
        matchmaking_url = self.endpoints["matchmaking"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(matchmaking_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            # host then cancels
            self.auth(username=host_name)
            self.delete(matchmaking_url, expected_status_code=http_client.NO_CONTENT)


class MockGameLiftClient(object):
    def __init__(self, *args, **kwargs):
        self.region = args[0]

    # For quick reference: https://docs.aws.amazon.com/gamelift/latest/apireference/API_StartMatchmaking.html
    def start_matchmaking(self, **kwargs):
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
        sample_response_from_gamelift  = """
        {
            'MatchmakingTicket': {
                'TicketId': '54a1351b-e271-489c-aa3e-e3c2cfa3c64f',
                'ConfigurationName': 'test',
                'ConfigurationArn': 'arn:aws:gamelift:eu-west-1:331925803394:matchmakingconfiguration/test',
                'Status': 'QUEUED',
                'StartTime': datetime.datetime(2021, 4, 23, 15, 1, 0, 460000, tzinfo=tzlocal()),
                'Players': [{
                    'PlayerId': '1',
                    'PlayerAttributes': {
                        'skill': {'N': 50.0}
                    },
                    'LatencyInMs': {}
                }]
            },
            'ResponseMetadata': {
                'RequestId': '675a758b-a5b9-4934-9167-beb5657016a3',
                'HTTPStatusCode': 200,
                'HTTPHeaders': {
                    'x-amzn-requestid': '675a758b-a5b9-4934-9167-beb5657016a3',
                    'content-type': 'application/x-amz-json-1.1',
                    'content-length': '323',
                    'date': 'Fri, 23 Apr 2021 15:00:59 GMT'
                },
                'RetryAttempts': 0
            }
        }
        """
        # MEMO TO SELF: the current processor re-uses the status field in redis for ticket events later, so we never actually see the status, just the latest mm event
        return {
            "MatchmakingTicket": {
                "TicketId": str(uuid.uuid4()),
                "ConfigurationName": kwargs["ConfigurationName"],
                "ConfigurationArn": f"arn:aws:gamelift:{self.region}:331925803394:matchmakingconfiguration/{kwargs['ConfigurationName']}",
                "Status": "QUEUED",  # Docs say the ticket will always be created with status QUEUED;
                "Players": kwargs["Players"]
            },
            "ResponseMetadata": {
                "RequestId": str(uuid.uuid4()),
                "HTTPStatusCode": 200,
            }
        }

    def stop_matchmaking(self, **kwargs):
        sample_response = """
        {
            'ResponseMetadata': {
                'RequestId': 'c4270121-4e6c-4dea-8fd2-98d764c2b0ca', 
                'HTTPStatusCode': 200, 
                'HTTPHeaders': {
                    'x-amzn-requestid': 'c4270121-4e6c-4dea-8fd2-98d764c2b0ca', 
                    'content-type': 'application/x-amz-json-1.1', 
                    'content-length': '2', 
                    'date': 'Fri, 23 Apr 2021 15:06:18 GMT'
                }, 
                'RetryAttempts': 0
            }
        }
        """
        return {
            'ResponseMetadata': {
                'RequestId': str(uuid.uuid4()),
                'HTTPStatusCode': 200
            }
        }