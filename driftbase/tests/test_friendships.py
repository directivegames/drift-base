import re
import uuid
from six.moves import http_client

from driftbase.utils.test_utils import BaseCloudkitTest

class _BaseFriendsTest(BaseCloudkitTest):
    def __init__(self, *args, **kwargs):
        super(_BaseFriendsTest, self).__init__(*args, **kwargs)
        self._created_players = set()

    def tearDown(self):
        for player in self._created_players:
            self.auth(player)
            for friend in self.get(self.endpoints["my_friends"]).json():
                self.delete(friend["friendship_url"], expected_status_code=http_client.NO_CONTENT)
            invite_url = self.endpoints["friend_invites"]
            for invite in self.get(invite_url).json():
                self.delete("%s/%d" % (invite_url, invite["id"]), expected_status_code=http_client.NO_CONTENT)
        self._created_players.clear()

    def make_player(self, username=None, player_name=None):
        super(_BaseFriendsTest, self).make_player(username, player_name)
        self._created_players.add(username)

    def issue_global_token(self):
        return self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()["token"]

    def create_friendship(self, requesting_username=None, receiving_username=None):
        receiving_player_id = None
        params = {}
        if receiving_username is not None:
            # Requires existing player, create it.
            self.make_player(username=receiving_username)
            receiving_player_id = self.player_id
            params["player_id"] = receiving_player_id
        # Issue a friend request
        self.make_player(username=requesting_username)
        requesting_player_id = self.player_id
        result = self.post(self.endpoints["friend_invites"], params=params, expected_status_code=http_client.CREATED).json()
        token = result["token"]
        # Accept friend request
        self.auth(username=receiving_username)
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.CREATED)
        return requesting_player_id, receiving_player_id, result.json()



class FriendRequestsTest(_BaseFriendsTest):
    """
    Tests for the /friend_invites endpoint
    """
    def test_create_global_token(self):
        # Create player for test
        self.make_player(username="Number one user")
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        self.assertIsInstance(result, dict)
        pattern = re.compile('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)
        self.assertTrue(pattern.match(result["token"]), "Token '{}' doesn't match the expected uuid format".format(result["token"]))

    def test_delete_token(self):
        self.make_player(username="Number one user")
        # create a token
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        # delete the token
        self.delete(result['url'], expected_status_code=http_client.NO_CONTENT)
        # delete it again
        self.delete(result['url'], expected_status_code=http_client.GONE)

    def test_other_player_may_not_delete_global_token(self):
        self.make_player(username="Number one user")
        # create a token
        result = self.post(self.endpoints["friend_invites"], expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.make_player(username="Number two user")
        # delete the token
        self.delete(invite_url, expected_status_code=http_client.FORBIDDEN)

    def test_other_player_may_not_delete_token_to_third_party(self):
        self.make_player(username="Number one user")
        receiving_player_id = self.player_id
        self.make_player(username="Number two user")
        # create a invite from user two to user one
        result = self.post(self.endpoints["friend_invites"], params={"player_id": receiving_player_id}, expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.make_player(username="Number three user")
        # delete the token as user three
        self.delete(invite_url, expected_status_code=http_client.FORBIDDEN)

    def test_receiving_player_can_delete_token(self):
        self.make_player(username="Number one user")
        receiving_player_id = self.player_id
        self.make_player(username="Number two user")
        # create a invite from two to one
        result = self.post(self.endpoints["friend_invites"], params={"player_id": receiving_player_id}, expected_status_code=http_client.CREATED).json()
        invite_url = result['url']
        self.auth(username="Number one user")
        # delete the token as user one
        self.delete(invite_url, expected_status_code=http_client.NO_CONTENT)

    def test_create_friend_request(self):
        # Create players for test
        self.make_player(username="Number one user")
        receiving_player_id = self.player_id
        self.make_player(username="Number two user")
        # Test basic success case
        result = self.post(self.endpoints["friend_invites"],
                           params={"player_id": receiving_player_id},
                           expected_status_code=http_client.CREATED).json()
        self.assertIsInstance(result, dict)
        pattern = re.compile('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)
        self.assertTrue(pattern.match(result["token"]), "Token '{}' doesn't match the expected uuid format".format(result["token"]))

    def test_cannot_send_request_to_self(self):
        self.make_player(username="Number one user")
        self.post(self.endpoints["friend_invites"],
                  params={"player_id": self.player_id},
                  expected_status_code=http_client.CONFLICT)

    def test_cannot_send_friend_request_to_friend(self):
        sender_id, receiver_id, results = self.create_friendship("Number one user", "Number two user")
        self.auth(username="Number two user")
        # Try to send a friend_request to our new friend
        self.post(self.endpoints["friend_invites"], params={"player_id": sender_id}, expected_status_code=http_client.CONFLICT)

    def test_cannot_have_multiple_pending_invites_to_same_player(self):
        self.make_player(username="Number one user")
        player1_id = self.player_id
        self.make_player(username="Number two user")
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
        self.make_player(username="Number one user")
        self.post(self.endpoints["friend_invites"],
                                               params={"player_id": 1234567890},
                                               expected_status_code=http_client.BAD_REQUEST)

    def test_cannot_have_reciprocal_invites(self):
        self.make_player(username="Number one user")
        player1_id = self.player_id
        self.make_player(username="Number two user")
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
        self.make_player(username="Number one user")
        player1_id = self.player_id
        self.make_player(username="Number two user")
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
        self.make_player(username="Number one user")
        player1_id = self.player_id
        self.make_player(username="Number two user")
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
        self.make_player(username="Number one user", player_name="Dr. Evil")
        player1_id = self.player_id
        player1_name = self.player_name
        self.make_player(username="Number two user", player_name="Mini Me")
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
        self.make_player(username="Number one user", player_name="Dr. Evil")
        player1_id = self.player_id
        player1_name = self.player_name
        self.make_player(username="Number two user", player_name="Mini Me")
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
    Tests for the /friendships endpoint
    """
    def test_no_friends(self):
        # Create players for test
        self.make_player(username="Number one user")

        # Should have no friends
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)

    def test_add_friend(self):
        # Create players for test
        self.make_player(username="Number one user")
        p1 = self.player_id
        token1 = self.issue_global_token()

        self.make_player(username="Number two user")
        p2 = self.player_id
        token2 = self.issue_global_token()

        self.make_player(username="Number four user")
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

    def test_add_friend_via_player_specific_token(self):
        # Create players for test
        self.make_player(username="Number one user")
        receiving_player_id = self.player_id
        self.make_player(username="Number two user")
        # Send friend request
        result = self.post(self.endpoints["friend_invites"],
                           params={"player_id": receiving_player_id},
                           expected_status_code=http_client.CREATED).json()
        # Login as receiver and accept friend request
        self.auth(username="Number one user")
        self.post(self.endpoints["my_friends"], data={"token": result["token"]}, expected_status_code=http_client.CREATED)

    def test_delete_friend(self):
        # Create friendship
        friendly_user, other_user = "friendly user", "deleting user"
        friendly_id, other_id, result = self.create_friendship(friendly_user, other_user)
        friendship_url = result["url"]

        # both players can end the relationship, first try friendly guy
        self.auth(friendly_user)
        response = self.delete(friendship_url, expected_status_code=http_client.NO_CONTENT)
        self.assertIn("application/json", response.headers["Content-Type"])
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)
        # delete friend again
        self.delete(friendship_url, expected_status_code=http_client.GONE)

        # other player should not have you as friend anymore
        self.auth(other_user)
        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)
        # other player tries to delete the same friendship results in it being GONE
        self.delete(friendship_url, expected_status_code=http_client.GONE)

        # recreate the friendship and test ending it via other user
        friendly_id, other_id, result = self.create_friendship(friendly_user, other_user)
        friendship_url = result["url"]
        self.auth(other_user)
        response = self.delete(friendship_url, expected_status_code=http_client.NO_CONTENT)

    def test_cannot_add_self_as_friend(self):
        # Create player for test
        self.make_player(username="Number four user")
        token = self.issue_global_token()

        # add self as friend
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.FORBIDDEN)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "You cannot befriend yourself!")

    def test_cannot_add_player_as_friend_with_invalid_token(self):
        # Create players for test
        self.make_player(username="Number one user")
        self.make_player(username="Number four user")

        token = str(uuid.uuid4())

        # add exiting player as friend, but use invalid token
        result = self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.NOT_FOUND)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "The invite was not found!")

    def test_adding_same_friend_twice_changes_nothing(self):
        # Create players for test
        self.make_player(username="Number one user")
        p1 = self.player_id
        token = self.issue_global_token()
        self.make_player(username="Number five user")
        # add a friend
        self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.CREATED)
        # add same friend again
        self.post(self.endpoints["my_friends"], data={"token": token}, expected_status_code=http_client.OK)

        friends = self.get(self.endpoints["my_friends"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], p1)

    def test_friendship_response_schema(self):
        sender_id, receiver_id, result = self.create_friendship("Number one user", "Number two user")
        friendship_url = result["url"]
        response = self.get(friendship_url).json()
        expected_keys = {"friendship_url", "friend_id", "friend_url", "spectate_url"}
        self.assertSetEqual(expected_keys, set(response.keys()))
