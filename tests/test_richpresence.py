import http.client as http_client
from driftbase.utils.test_utils import BaseCloudkitTest
import driftbase.richpresence as rp
from driftbase.api.richpresence import PlayerRichPresence, RichPresenceSchema
from werkzeug.local import LocalProxy
from flask import g
from drift.core.extensions.driftconfig import get_config_for_request
from drift.core.resources.postgres import get_sqlalchemy_session
from drift.core.resources.redis import get_redis_session
from contextlib import contextmanager
from driftbase.messages import fetch_messages
import gevent
from drift.utils import get_config

class RichPresenceTest(BaseCloudkitTest):
    """
    Tests for the /rich-presence endpoints and related implementation.
    """

    def _get_player_richpresence(self, player_id : int):
        self.auth()
        url = self.endpoints['template_richpresence'].replace("{player_id}", str(player_id))
        return self.get(url).json()

    def _make_token(self):
        return self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()["token"]

    @contextmanager
    def _app_context(self):
        with self.drift_app.app_context() as ctx:
            drift_config = self.drift_app.extensions['driftconfig']
            ctx.driftconfig = get_config()
            yield ctx

    @contextmanager
    def _request_context(self, *args, **kwargs):
        with self._app_context():
            if "path" not in kwargs:
                kwargs["path"] = "/test/endpoint"
            with self.drift_app.test_request_context(*args, **kwargs) as request_ctx:
                g.conf = LocalProxy(get_config_for_request)
                g.db = LocalProxy(get_sqlalchemy_session)
                g.redis = LocalProxy(get_redis_session)
                try:
                    yield request_ctx
                finally:
                    gevent.idle()

    def _get_message_queue_url(self, player_id : int, message_id : int = 1) -> str:
        """
        Returns a formatted 
        """
        url : str = self.endpoints['template_get_message'] \
            .replace('{exchange}', "players") \
            .replace('{exchange_id}', str(player_id)) \
            .replace('{queue}', 'richpresence') \
            .replace('{message_id}', str(message_id))

        return url

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
        match_id = match["match_id"]
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

        with self._request_context():
            res = self._get_player_richpresence(player_id)

            # If these starts failing, check the defaults in _create_match
            self.assertEqual(res['map_name'], "map_name")
            self.assertEqual(res['game_mode'], "game_mode")

        # Remove player, and re-confirm status
        self.auth_service()
        self.delete(matchplayer_url, expected_status_code=http_client.OK)

        with self._request_context():
            res = self._get_player_richpresence(player_id)
            self.assertEqual(res['map_name'], "")
            self.assertEqual(res['game_mode'], "")

    def test_richpresence_messagequeue(self):
        """
        Tests that updating rich-presence will send a message to your friends.
        """
        
        self.auth()
        
        # Setup players
        self.auth(username="player_friend")
        friend_id = self.player_id
        friend_token = self._make_token()

        self.auth(username="player_self")
        player_id = self.player_id

        # Create friend relationship
        self.post(self.endpoints["my_friends"], data={"token": friend_token}, expected_status_code=http_client.CREATED)

        # Set rich presence, and confirm change via redis
        presence = PlayerRichPresence(True, True, "pushback", "dizzyheights")
        with self._request_context():
            rp.set_richpresence(friend_id, presence)
            self.assertTrue(presence, rp.get_richpresence(friend_id))

        # Ensure that the message was recieved, and matches expected presence
        url = self._get_message_queue_url(player_id)
        payload = self.get(url).json()["payload"]

        self.assertTrue(presence, RichPresenceSchema(many=False).load(payload))


    def test_rich_presence(self):
        """
        Tests whether the players active presence information is correct.
        """
        # Assert that an offline player has expected rich presence
        self.auth()

        player_id = self.player_id
        presence = self._get_player_richpresence(player_id)
        self.assertFalse(presence["is_online"])
        self.assertFalse(presence["is_in_game"])
        self.assertEqual(presence["game_mode"], "")
        self.assertEqual(presence["map_name"], "")

        # Assert that an online player has expected rich presence
        self.make_player()

        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        teams_url = match["teams_url"]
        resp = self.get(match_url).json()

        matchplayers_url = resp["matchplayers_url"]

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED).json()
        team_id = resp["team_id"]
        resp = self.get(teams_url).json()

        data = {"player_id": player_id, "team_id": team_id}
        resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED).json()
        
        presence = self._get_player_richpresence(player_id)

        player = self.get(self.endpoints["my_player"]).json()
        match_player = self.get(matchplayers_url).json()[0]

        self.assertEqual(presence["is_online"], player["is_online"])

        self.assertEqual(presence["is_in_game"], match_player["status"] == "active")
        self.assertTrue(presence["is_in_game"])

        self.assertNotEqual(presence["game_mode"], "") # Test matches have dummy data for these fields (see _create_match)
        self.assertNotEqual(presence["map_name"], "")