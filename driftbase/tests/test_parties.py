import re
import uuid

from six.moves import http_client

from driftbase.utils.test_utils import BaseCloudkitTest


class PartiesTest(BaseCloudkitTest):
    """
    Tests for the /parties endpoint
    """
    def test_create_adds_creating_player_to_party(self):
        # Create player for test
        self.auth(username="Number one user")

        result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()

        self.assertIsNotNone(result.get('url'))
        self.assertIsNotNone(result.get('invites_url'))
        self.assertIsNotNone(result.get('players_url'))

        # Check there's only one player in the party, and it's the player who created it
        players = self.get(result['players_url'], expected_status_code=http_client.OK).json()

        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]['player_id'], self.player_id)

    def test_invite_players_to_party(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id

        self.auth(username="Number two user")
        p2 = self.player_id

        # Create a party
        result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
        party_url = result['url']

        # Player 2 invites player 1 to the party
        invite = self.post(result['invites_url'], data={"player_id": p1}, expected_status_code=http_client.CREATED).json()
        invite_url = invite.get('url')
        self.assertIsNotNone(invite_url)

        # Check that player 1 got the invite
        self.auth(username="Number one user")

        def validator(payload):
            self.assertEqual(payload['party_url'], party_url)
            self.assertEqual(payload['invite_url'], invite_url)
            self.assertEqual(payload['inviting_player_id'], p2)

        notification = self.check_party_notification('invite', validator)
        self.assertIsNotNone(notification)

        # Accept the invite
        self.patch(notification['invite_url'], data={}, expected_status_code=http_client.OK)

        # Check that player 2 gets a notification when player 1 accepts the invite
        self.auth(username="Number two user")

        def validator(payload):
            self.assertEqual(payload['party_url'], party_url)
            self.assertEqual(payload['player_id'], p1)
            return True

        self.check_party_notification('player_joined', validator)

    def test_decline_invite(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id

        self.auth(username="Number two user")
        p2 = self.player_id

        # Create a party
        result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
        party_url = result['url']

        # Player 2 invites player 1 to the party
        invite = self.post(result['invites_url'], data={"player_id": p1}, expected_status_code=http_client.CREATED).json()
        invite_url = invite.get('url')

        # Player 1 declines the invite
        self.auth(username="Number one user")
        notification = self.get_party_notification('invite')
        self.delete(notification['invite_url'], expected_status_code=http_client.OK)

        # Check that player 2 gets a notification when player 1 declines
        self.auth(username="Number two user")

        def validator(payload):
            self.assertEqual(payload['party_url'], party_url)
            self.assertEqual(payload['player_id'], p1)
            return True

        notification = self.check_party_notification('invite_declined', validator)
        self.assertIsNotNone(notification)

    def get_party_notification(self, event):
        notification = None
        messages = self.get(self.endpoints["my_messages"]).json()
        topic = messages.get('party_notification', [])
        for message in topic:
            payload = message.get('payload', {})
            if payload.get('event', None) == event:
                notification = payload
                break
        return notification

    def check_party_notification(self, event, validator):
        notification = self.get_party_notification(event)
        self.assertIsNotNone(notification)
        validator(notification)
        return notification