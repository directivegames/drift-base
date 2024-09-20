import http.client as http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from driftbase.richpresence import RichPresenceService
from driftbase.richpresence import PlayerRichPresence, RichPresenceSchema
from flask import url_for, g
from driftbase.utils.exceptions import ForbiddenException, NotFoundException
import uuid

class BaseRichPresenceTest(BaseCloudkitTest):
        
    def _make_named_player(self, username, player_name=None):
        self.auth(username=username, player_name=player_name)
        self.patch(self.endpoints['my_player'], data={"name": player_name or username})
        return self.player_id
        
    def _get_player_richpresence(self, player_id : int) -> dict:
        url = self.endpoints['template_richpresence'].replace("{player_id}", str(player_id))
        return self.get(url).json()

    def _get_message_queue_url(self, player_id : int, message_id : int = 1) -> str:
        with self._request_context():
            return url_for("messages.message", exchange_id=player_id, exchange="players", queue="richpresence", message_id=message_id, _external=True)

    def _make_user_name(self, name):
        return "{}.{}".format(str(uuid.uuid4())[:8], name)


class RichPresenceIsOnline(BaseRichPresenceTest):
    def test_richpresence_is_online(self):
        """
        Test that a player will become online based on his client status
        """

        username = self._make_user_name("a")

        # Create a client
        self._make_named_player(username)
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
        rich_presence = self._get_player_richpresence(player_id)
        self.assertTrue(rich_presence['is_online'], "is_online should be true for online client.")
        self.assertFalse(rich_presence['is_in_game'], "is_in_game should be false for online client.")

        # Update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti
        r = self.get("/")
        self.assertEqual(client_url, r.json()["endpoints"]["my_client"])
        self.delete(client_url)

        # Ensure client is considered offline post deletion
        rich_presence = self._get_player_richpresence(player_id)
        self.assertFalse(rich_presence['is_online'], "is_online should be false for offline client.")
        self.assertFalse(rich_presence['is_in_game'], "is_online should be false for offline client.")

class RichPresenceMatchUpdate(BaseRichPresenceTest):
    def test_richpresence_match_update(self):
        """
        Tests that the players rich presence is updated when he joins a match, and when he leaves
        a match.
        """

        username = "test_richpresence_match_update"
        self.auth(username=username)
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

        self.auth(username=username)
        res = self._get_player_richpresence(player_id)

        # If these starts failing, check the defaults in _create_match
        self.assertEqual(res['map_name'], "map_name")
        self.assertEqual(res['game_mode'], "game_mode")
        self.assertEqual(res['is_in_game'], True)

        # Remove player, and re-confirm status
        self.auth_service()
        self.delete(matchplayer_url, expected_status_code=http_client.OK)

        self.auth(username=username)

        res = self._get_player_richpresence(player_id)
        self.assertEqual(res['map_name'], "")
        self.assertEqual(res['game_mode'], "")
        self.assertEqual(res['is_in_game'], False)

class RichPresenceMessageQueue(BaseRichPresenceTest):
    def test_richpresence_messagequeue(self):
        """
        Tests that updating rich-presence will send a message to your friends.
        """
        
        friend_username = self._make_user_name("f")
        self_username = self._make_user_name("s")

        # Setup players
        friend_id = self._make_named_player(friend_username)
        friend_token = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()["token"]

        player_id = self._make_named_player(self_username)

        # Create friend relationship
        self.post(self.endpoints["my_friends"], data={"token": friend_token}, expected_status_code=http_client.CREATED)

        # Set rich presence, and confirm change via redis
        presence = PlayerRichPresence(friend_id, True, True, "pushback", "dizzyheights")
        
        with self._request_context():
            current_user_mock = {
                "player_id": player_id
            }
            RichPresenceService(g.db, g.redis, current_user_mock).set_richpresence(friend_id, presence)
            
            res = RichPresenceService(g.db, g.redis, current_user_mock).get_richpresence(friend_id)
            self.assertEqual(presence, res)

        # Ensure that the message was recieved, and matches expected presence
        url = self._get_message_queue_url(player_id)
        payload = self.get(url).json()["payload"]

        res = RichPresenceSchema(many=False).load(payload)
        self.assertEqual(presence, res)

class RichPresenceNoAccess(BaseRichPresenceTest):
    def test_richpresence_noaccess(self):
        """
        Tests that it's impossible to get rich-presence information for non-friends.
        """
        self.auth(username="player_self")
        player_id = self.player_id
        fake_friend_id = 100

        with self._request_context():
            current_user_mock = {
                "player_id": player_id
            }
            self.assertRaises(NotFoundException, RichPresenceService(g.db, g.redis, current_user_mock).get_richpresence, fake_friend_id)

        self.auth(username="non_friend")
        non_friend = self.player_id

        ## Test with player role
        with self._request_context():
            current_user_mock = {
                "player_id": player_id,
                "roles": ["player"]
            }
            self.assertRaises(ForbiddenException, RichPresenceService(g.db, g.redis, current_user_mock).get_richpresence, non_friend)

        ## Test with system role
        with self._request_context():
            current_user_mock = {
                "player_id": player_id,
                "roles": ["service"]
            }

            try:
                RichPresenceService(g.db, g.redis, current_user_mock).get_richpresence(non_friend)
            except ForbiddenException:
                self.fail("get_richpresence raised RichPresenceService as a system")