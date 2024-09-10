import http.client as http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from driftbase.richpresence import RichPresenceService
from driftbase.richpresence import PlayerRichPresence, RichPresenceSchema
from flask import url_for, g

class RichPresenceTest(BaseCloudkitTest):
    """
    Tests for the /rich-presence endpoints and related implementation.
    """

    def _get_player_richpresence(self, player_id : int) -> dict:
        self.auth()
        url = self.endpoints['template_richpresence'].replace("{player_id}", str(player_id))
        return self.get(url).json()

    def _get_message_queue_url(self, player_id : int, message_id : int = 1) -> str:
        with self._request_context():
            return url_for("messages.message", exchange_id=player_id, exchange="players", queue="richpresence", message_id=message_id, _external=True)

    def test_richpresence_is_online(self):
        """
        Test that a player will become online based on his client status
        """

        # Create a client
        self.auth()
        player_id = self.player_id
        clients_uri = self.endpoints["clients"]
        platform_version = "1.20.22"
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version",
            "platform_version": platform_version,
            "platform_info": {},
        }
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        client_url = r.json()["url"]

        # Ensure client is considered online
        self.assertTrue(self._get_player_richpresence(player_id)['is_online'])

        # Update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti
        r = self.get("/")
        self.assertEqual(client_url, r.json()["endpoints"]["my_client"])
        self.delete(client_url)

        # Ensure client is considered offline post deletion
        self.assertFalse(self._get_player_richpresence(player_id)['is_online'])

    def test_richpresence_match_update(self):
        """
        Tests that the players rich presence is updated when he joins a match, and when he leaves
        a match.
        """

        self.auth()
        player_id = self.player_id
        team_id = 0

        # Create a match, and add self
        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        teams_url = match["teams_url"]
        resp = self.get(match_url).json()

        matchplayers_url = resp["matchplayers_url"]

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED).json()
        team_id = resp["team_id"]
        resp = self.get(teams_url).json()

        data = {"player_id": player_id,
                "team_id": team_id
                }
        resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED).json()
        matchplayer_url = resp["url"]

        res = self._get_player_richpresence(player_id)

        # If these starts failing, check the defaults in _create_match
        self.assertEqual(res['map_name'], "map_name")
        self.assertEqual(res['game_mode'], "game_mode")

        # Remove player, and re-confirm status
        self.auth_service()
        self.delete(matchplayer_url, expected_status_code=http_client.OK)

        res = self._get_player_richpresence(player_id)
        self.assertEqual(res['map_name'], "")
        self.assertEqual(res['game_mode'], "")

    def test_richpresence_messagequeue(self):
        """
        Tests that updating rich-presence will send a message to your friends.
        """
                
        # Setup players
        self.auth(username="player_friend")
        friend_id = self.player_id
        friend_token = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()["token"]

        self.auth(username="player_self")
        player_id = self.player_id

        # Create friend relationship
        self.post(self.endpoints["my_friends"], data={"token": friend_token}, expected_status_code=http_client.CREATED)

        # Set rich presence, and confirm change via redis
        presence = PlayerRichPresence(True, True, "pushback", "dizzyheights")
        with self._request_context():
            RichPresenceService(g.db, g.redis).set_richpresence(friend_id, presence)
            self.assertTrue(presence, RichPresenceService(g.db, g.redis).get_richpresence(friend_id))

        # Ensure that the message was recieved, and matches expected presence
        url = self._get_message_queue_url(player_id)
        payload = self.get(url).json()["payload"]

        self.assertTrue(presence, RichPresenceSchema(many=False).load(payload))