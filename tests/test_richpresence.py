import http.client as http_client
from driftbase.utils.test_utils import BaseCloudkitTest

class PlayersTest(BaseCloudkitTest):
    """
    Tests for the /rich-presence endpoints
    """

    def _get_player_rich_presence(self, player_id : int):
        self.auth()
        url = self.endpoints['template_richpresence'].replace("{player_id}", str(player_id))
        return self.get(url).json()

    def test_nothing(self):
        self.auth()
        self.assertTrue(True)
        
    def test_rich_presence(self):
        """
        Tests whether the players active presence information is correct.
        """
        # Assert that an offline player has expected rich presence
        self.auth()

        player_id = self.player_id
        presence = self._get_player_rich_presence(player_id)
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
        
        presence = self._get_player_rich_presence(player_id)

        player = self.get(self.endpoints["my_player"]).json()
        match_player = self.get(matchplayers_url).json()[0]

        self.assertEqual(presence["is_online"], player["is_online"])

        self.assertEqual(presence["is_in_game"], match_player["status"] == "active")
        self.assertTrue(presence["is_in_game"])

        self.assertNotEqual(presence["game_mode"], "") # Test matches have dummy data for these fields (see _create_match)
        self.assertNotEqual(presence["map_name"], "")