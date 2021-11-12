import re
import uuid
import copy
import http.client as http_client
from unittest.mock import patch
from driftbase import friendships
from driftbase.exceptions import drift_api_exceptions

from driftbase.utils.test_utils import BaseCloudkitTest

class _BaseFriendsTest(BaseCloudkitTest):
    def __init__(self, *args, **kwargs):
        super(_BaseFriendsTest, self).__init__(*args, **kwargs)
        self._logged_in = []

    def tearDown(self):
        for player in self._logged_in[:]:
            self.auth(player)
            for friend in self.get(self.endpoints["my_friends"]).json():
                self.delete(friend["friendship_url"], expected_status_code=http_client.NO_CONTENT)
            invite_url = self.endpoints["friend_invites"]
            for invite in self.get(invite_url).json():
                self.delete("%s/%d" % (invite_url, invite["id"]), expected_status_code=http_client.NO_CONTENT)
        self._logged_in = []

    def auth(self, username=None, player_name=None):
        super(_BaseFriendsTest, self).auth(username, player_name)
        if player_name is not None:
            self.patch(self.endpoints["my_player"], data={"name": player_name})
        self._logged_in.append(username)

    def make_token(self):
        return self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()["token"]


class FriendRequestsTest(_BaseFriendsTest):
    """
    Tests for the /friend_invites endpoint
    """
    def test_create_global_token(self):
        # Create player for test
        self.auth(username="Number one user")
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        self.assertIsInstance(result, dict)
        pattern = re.compile('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)
        self.assertTrue(pattern.match(result["token"]), "Token '{}' doesn't match the expected uuid format".format(result["token"]))

    def test_delete_token(self):
        self.auth(username="Number one user")
        # create a token
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        # delete the token
        self.delete(result['url'], expected_status_code=http_client.NO_CONTENT)
        # delete it again
        self.delete(result['url'], expected_status_code=http_client.GONE)

    def test_other_player_may_not_delete_global_token(self):
        self.auth(username="Number one user")
        # create a token
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.auth(username="Number two user")
        # delete the token
        self.delete(invite_url, expected_status_code=http_client.FORBIDDEN)

    def test_other_player_may_not_delete_token_to_third_party(self):
        self.auth(username="Number one user")
        receiving_player_id = self.player_id
        self.auth(username="Number two user")
        # create a invite from user two to user one
        result = self.post(self.endpoints["friend_invites"], params = {"player_id": receiving_player_id}, expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.auth(username="Number three user")
        # delete the token as user three
        self.delete(invite_url, expected_status_code=http_client.FORBIDDEN)

    def test_receiving_player_can_delete_token(self):
        self.auth(username="Number one user")
        receiving_player_id = self.player_id
        self.auth(username="Number two user")
        # create a invite from two to one
        result = self.post(self.endpoints["friend_invites"], params={"player_id": receiving_player_id}, expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.auth(username="Number one user")
        # delete the token as user one
        self.delete(invite_url, expected_status_code=http_client.NO_CONTENT)

    def test_create_friend_request(self):
        # Create players for test
        self.auth(username="Number one user")
        receiving_player_id = self.player_id
        self.auth(username="Number two user")
        # Test basic success case
        result = self.post(self.endpoints["friend_invites"],
                           params={"player_id": receiving_player_id},
                           expected_status_code=http_client.CREATED).json()
        self.assertIsInstance(result, dict)
        pattern = re.compile('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)
        self.assertTrue(pattern.match(result["token"]), "Token '{}' doesn't match the expected uuid format".format(result["token"]))

    def test_cannot_send_request_to_self(self):
        self.auth(username="Number one user")
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": self.player_id},
                  expected_status_code=http_client.CONFLICT)

    def test_cannot_send_friend_request_to_friend(self):
        # Create friendship
        self.auth(username="Number one user")
        player1_id = self.player_id
        token1 = self.make_token()
        self.auth(username="Number two user")
        self.post(self.endpoints["my_friends"], data={"token": token1}, expected_status_code=http_client.CREATED)
        # Try to send a friend_request to our new friend
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": player1_id},
                  expected_status_code=http_client.CONFLICT)

    def test_cannot_have_multiple_pending_invites_to_same_player(self):
        self.auth(username="Number one user")
        player1_id = self.player_id
        self.auth(username="Number two user")
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": player1_id},
                  expected_status_code=http_client.CREATED)
        # Try to create another one to him
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": player1_id},
                  expected_status_code=http_client.CONFLICT)

    def test_cannot_send_request_to_non_existent_player(self):
        from sqlalchemy import exc
        self.auth(username="Number one user")
        self.post(self.endpoints["friend_invites"],
                                               params={"player_id": 1234567890},
                                               expected_status_code=http_client.BAD_REQUEST)

    def test_cannot_have_reciprocal_invites(self):
        self.auth(username="Number one user")
        player1_id = self.player_id
        self.auth(username="Number two user")
        player2_id = self.player_id
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": player1_id},
                  expected_status_code=http_client.CREATED)
        self.auth(username="Number one user")
        # Should fail at creating invite from 1 to 2
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": player2_id},
                  expected_status_code=http_client.CONFLICT)

    def test_get_issued_tokens(self):
        self.auth(username="Number one user")
        player1_id = self.player_id
        self.auth(username="Number two user")
        player2_id = self.player_id
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"], params={"player_id": player1_id}, expected_status_code=http_client.CREATED)
        result = self.get(self.endpoints["friend_invites"], expected_status_code=http_client.OK).json()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) == 1)
        self.assertIsInstance(result[0], dict)
        invite = result[0]
        self.assertTrue(invite["issued_by_player_id"] == player2_id)
        self.assertTrue(invite["issued_to_player_id"] == player1_id)

    def test_get_pending_requests(self):
        self.auth(username="Number one user")
        player1_id = self.player_id
        self.auth(username="Number two user")
        player2_id = self.player_id
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"], params={"player_id": player1_id}, expected_status_code=http_client.CREATED)
        # auth as player 1 and fetch its friend requests
        self.auth(username="Number one user")
        result = self.get(self.endpoints["friend_requests"], expected_status_code=http_client.OK).json()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) == 1)
        self.assertIsInstance(result[0], dict)
        request = result[0]
        self.assertTrue(request["issued_by_player_id"] == player2_id)
        self.assertTrue(request["issued_to_player_id"] == self.player_id)
        self.assertTrue(request["accept_url"].endswith("/friendships/players/%d" % self.player_id))

    def test_invite_response_schema(self):
        self.auth(username="Number one user", player_name="Dr. Evil")
        player1_id = self.player_id
        player1_name = self.player_name
        self.auth(username="Number two user", player_name="Mini Me")
        player2_id = self.player_id
        player2_name = self.player_name
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"], params={"player_id": player1_id}, expected_status_code=http_client.CREATED)
        response = self.get(self.endpoints["friend_invites"], expected_status_code=http_client.OK).json()
        self.assertIsInstance(response, list)
        self.assertTrue(len(response) == 1)
        invite = response[0]
        expected_keys = {"id", "create_date", "expiry_date", "modify_date", "token",
                         "issued_by_player_id", "issued_by_player_url", "issued_by_player_name",
                         "issued_to_player_id", "issued_to_player_url", "issued_to_player_name"}
        self.assertSetEqual(expected_keys, set(invite.keys()))
        self.assertTrue(invite["issued_by_player_id"] == player2_id)
        self.assertTrue(invite["issued_by_player_name"] == player2_name)
        self.assertTrue(invite["issued_to_player_id"] == player1_id)
        self.assertTrue(invite["issued_to_player_name"] == player1_name)


    def test_request_response_schema(self):
        self.auth(username="Number one user", player_name="Dr. Evil")
        player1_id = self.player_id
        player1_name = self.player_name
        self.auth(username="Number two user", player_name="Mini Me")
        player2_id = self.player_id
        player2_name = self.player_name
        # Create invite from 2 to 1
        self.post(self.endpoints["friend_invites"], params={"player_id": player1_id}, expected_status_code=http_client.CREATED)
        # Relog as 1
        self.auth(username="Number one user", player_name=player1_name)
        response = self.get(self.endpoints["friend_requests"], expected_status_code=http_client.OK).json()
        self.assertIsInstance(response, list)
        self.assertTrue(len(response) == 1)
        request = response[0]
        expected_keys = {"id", "create_date", "expiry_date", "modify_date", "token",
                         "issued_by_player_id", "issued_by_player_url", "issued_by_player_name",
                         "issued_to_player_id", "issued_to_player_url", "issued_to_player_name", "accept_url"}
        self.assertSetEqual(expected_keys, set(request.keys()))
        self.assertTrue(request["issued_by_player_id"] == player2_id)
        self.assertTrue(request["issued_by_player_name"] == player2_name)
        self.assertTrue(request["issued_to_player_id"] == self.player_id)
        self.assertTrue(request["issued_to_player_name"] == player1_name)
        self.assertTrue(request["accept_url"].endswith("/friendships/players/%d" % self.player_id))


class FriendsTest(_BaseFriendsTest):
    """
    Tests for the /friends endpoint
    """
    def test_no_friends(self):
        # Create players for test
        self.auth(username="Number one user")
        self.auth(username="Number two user")
        self.auth(username="Number three user")

        # Should have no friends
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)

    def test_add_friend(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id
        token1 = self.make_token()

        self.auth(username="Number two user")
        p2 = self.player_id
        token2 = self.make_token()

        self.auth(username="Number four user")
        player_id = self.player_id

        # add one friend
        self.post(self.endpoints["my_friends"], data={"token": token1}, expected_status_code=http_client.CREATED)

        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], p1)

        # add another friend
        self.post(self.endpoints["my_friends"], data={"token": token2}, expected_status_code=http_client.CREATED)

        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 2)
        self.assertTrue(friends[0]["friend_id"] in [p1, p2])
        self.assertTrue(friends[1]["friend_id"] in [p1, p2])
        self.assertTrue(friends[0]["friend_id"] != friends[1]["friend_id"])

        # check that first player is friends with you
        self.auth(username="Number one user")
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], player_id)

        # check that second player is friends with you
        self.auth(username="Number two user")
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], player_id)

    def test_delete_friend(self):
        # Create players for test
        self.auth(username="Number seven user")
        token = self.make_token()

        self.auth(username="Number six user")

        # add one friend
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.CREATED).json()

        # delete friend
        friendship_url = result["url"]
        response = self.delete(friendship_url, expected_status_code=http_client.NO_CONTENT)
        # Check if we get json type response
        self.assertIn("application/json", response.headers["Content-Type"])

        # delete friend again
        self.delete(friendship_url, expected_status_code=http_client.GONE)

        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)

        # other player should not have you as friend anymore
        self.auth(username="Number seven user")
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)

        # other player tries to delete the same friendship results in it being GONE
        self.delete(friendship_url, expected_status_code=http_client.GONE)

        self.auth(username="Number six user")

        # add friend back again
        self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.CREATED).json()
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)

    def test_cannot_add_self_as_friend(self):
        # Create player for test
        self.auth(username="Number four user")
        token = self.make_token()

        # add self as friend
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.FORBIDDEN)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "You cannot befriend yourself!")

    def test_cannot_add_player_as_friend_with_invalid_token(self):
        # Create players for test
        self.auth(username="Number one user")

        self.auth(username="Number four user")

        token = str(uuid.uuid4())

        # add exiting player as friend, but use invalid token
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.NOT_FOUND)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "The invite was not found!")

    def test_adding_same_friend_twice_changes_nothing(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id
        token = self.make_token()

        self.auth(username="Number five user")

        # add a friend
        self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.CREATED)
        # add same friend again
        self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.OK)

        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], p1)

class _BaseFriendsCodeTest(BaseCloudkitTest):
    friend_code = None
    friend_code_id = None
    friend_code_player_id = None
    friend_code_url = None

    def create_friend_code(self):
        response = self.post(self.endpoints["friend_codes"], expected_status_code=http_client.CREATED)
        response_json = response.json()

        self.friend_code = response_json
        self.friend_code_id = response_json["friend_code"]
        self.friend_code_player_id = response_json["player_id"]
        self.friend_code_url = response_json["friend_code_url"]

    def _assert_error(self, response, expected_description=None):
        response_json = response.json()

        self.assertIn("error", response_json)
        self.assertIsInstance(response_json["error"], dict)
        self.assertIn("description" ,response_json["error"])

        if expected_description:
            self.assertEqual(response_json["error"]["description"], expected_description)

"""
Friend codes API
"""

# /friendships/codes
class FriendCodesAPITest(_BaseFriendsCodeTest):
    # Get
    def test_get_api(self):
        self.make_player()
        friend_codes_url = self.endpoints["friend_codes"]

        with patch.object(friendships, "get_player_friend_code", return_value=MOCK_FRIEND_CODE) as get_player_friend_code_mock:
            # Valid
            response = self.get(friend_codes_url, expected_status_code=http_client.OK)
            response_json = response.json()

            self.assertIn("friend_code_url", response_json)

            # Not found
            get_player_friend_code_mock.side_effect = drift_api_exceptions.NotFoundException(MOCK_ERROR)

            response = self.get(friend_codes_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Post
    def test_post_api(self):
        self.make_player()
        friend_codes_url = self.endpoints["friend_codes"]

        with patch.object(friendships, "create_friend_code", return_value=MOCK_FRIEND_CODE) as create_friend_code_mock:
            # Valid
            response = self.post(friend_codes_url, expected_status_code=http_client.CREATED)
            response_json = response.json()

            self.assertIn("friend_code_url", response_json)

# /friendships/codes/<friend_code>
class FriendCodeAPITest(_BaseFriendsCodeTest):
    # Get
    def test_get_api(self):
        self.make_player()
        friend_code_url = self.endpoints["friend_codes"] + "/ABC123"

        with patch.object(friendships, "get_friend_code", return_value=MOCK_FRIEND_CODE) as get_friend_code_mock:
            # Valid
            response = self.get(friend_code_url, expected_status_code=http_client.OK)
            response_json = response.json()

            self.assertIn("friend_code_url", response_json)

            # Not found
            get_friend_code_mock.side_effect = drift_api_exceptions.NotFoundException(MOCK_ERROR)

            response = self.get(friend_code_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Post
    def test_post_api(self):
        self.make_player()
        friend_code_url = self.endpoints["friend_codes"] + "/ABC123"

        with patch.object(friendships, "use_friend_code", return_value=(420, 1337)) as create_friend_code_mock:
            # Valid
            response = self.post(friend_code_url, expected_status_code=http_client.CREATED)
            response_json = response.json()

            self.assertIn("friend_id", response_json)
            self.assertIn("url", response_json)
            self.assertIn("messagequeue_url", response_json)

            # Not found
            create_friend_code_mock.side_effect = drift_api_exceptions.NotFoundException(MOCK_ERROR)

            response = self.post(friend_code_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

"""
Friend codes implementation
"""

class FriendCodesTest(_BaseFriendsCodeTest):
    # Get friend code

    def test_get_player_friend_code(self):
        self.make_player()
        self.create_friend_code()

        # Get player friend code
        response = self.get(self.endpoints["friend_codes"], expected_status_code=http_client.OK)
        get_friend_code = response.json()

        self.assertDictEqual(self.friend_code, get_friend_code)
        self.assertIn("friend_code_url", get_friend_code)

        # Get specific friend code
        response = self.get(get_friend_code["friend_code_url"], expected_status_code=http_client.OK)
        get_specific_friend_code = response.json()

        self.assertDictEqual(get_specific_friend_code, get_friend_code)

    def test_get_player_friend_code_without_having_a_code(self):
        self.make_player()

        response = self.get(self.endpoints["friend_codes"], expected_status_code=http_client.NOT_FOUND)
        self._assert_error(response)

    def test_get_friend_code_that_doesnt_exist(self):
        self.make_player()

        response = self.get(self.endpoints["friend_codes"] + "/bogus", expected_status_code=http_client.NOT_FOUND)
        self._assert_error(response)

    # Create friend code

    def test_create_friend_code(self):
        self.make_player()
        self.create_friend_code()

        self.assertIn("friend_code_url", self.friend_code)
        self.assertIn("create_date", self.friend_code)
        self.assertIn("expiry_date", self.friend_code)
        self.assertIn("player_id", self.friend_code)
        self.assertIn("friend_code", self.friend_code)

    def test_create_friend_code_twice(self):
        self.make_player()

        # First create call
        self.create_friend_code()

        old_friend_code = copy.deepcopy(self.friend_code)

        # Second create call
        self.create_friend_code()

        # Should be the same
        self.assertDictEqual(old_friend_code, self.friend_code)

    # Use friend code

    def test_use_friend_code(self):
        player_1_username = self.make_player()
        player_1_id = self.player_id
        self.create_friend_code()

        player_2_username = self.make_player()
        player_2_id = self.player_id

        self.post(self.friend_code_url, expected_status_code=http_client.CREATED)

        # Verify that the players are friends

        # Player 2 friends list
        response = self.get(self.endpoints["my_friends"], expected_status_code=http_client.OK)
        friends_list = response.json()

        self.assertTrue(any(friend["friend_id"] == player_1_id for friend in friends_list))

        # Player 1 friends list
        self.auth(player_1_username)

        response = self.get(self.endpoints["my_friends"], expected_status_code=http_client.OK)
        friends_list = response.json()

        self.assertTrue(any(friend["friend_id"] == player_2_id for friend in friends_list))

    def test_use_friend_code_twice(self):
        self.make_player()
        self.create_friend_code()

        # Login second player
        self.make_player()

        # First use
        self.post(self.friend_code_url, expected_status_code=http_client.CREATED)

        # Second use
        response = self.post(self.friend_code_url, expected_status_code=http_client.CONFLICT)

        # Not asserting error because CONFLICT errors JSON is different from others. Really strange.
        # self._assert_error(response)

    def test_use_friend_code_that_doesnt_exist(self):
        self.make_player()

        response = self.post(self.endpoints["friend_codes"] + "/bogus", expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)


MOCK_FRIEND_CODE = {
    "friend_code": "ABC123",
    "player_id": 1337,
    "create_date": "2021-09-24T16:15:08.758448",
    "expiry_date": "2021-09-24T16:25:08.758448",
}

MOCK_FRIENDSHIP = {
    "friend_id": 1337,
    "url": "this is totally a url",
    "messagequeue_url": "this is also totally a url",
}

MOCK_ERROR = "Some error"
