import http.client
import urllib

from driftbase.api.messages2 import _next_message_id
from driftbase.utils.test_utils import BaseCloudkitTest


class Messages2Test(BaseCloudkitTest):
    """
    Tests for the /messages2 endpoints
    """

    def make_player_message_endpoint_and_session(self):
        self.make_player()
        return self.endpoints["my_player"], self.headers

    def get_messages_url(self, player_receiver_endpoint):
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue2_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages2_url"]
        return messagequeue_url_template, messages_url

    def test_messages_send(self):
        player_receiver_endpoint, _ = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        player_sender = self.make_player()

        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        message_url = r.json()["url"]

        # we should not be able to read the message back, only the recipient can do that
        r = self.get(message_url, expected_status_code=http.client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

        # we should not be able to read anything from the exchange either
        r = self.get(messages_url, expected_status_code=http.client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

    def test_messages_receive(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {
            "message": {"Hello": "World"}
        }
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED).json()
        message_url = r["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # Attempt to fetch just the message we just sent
        r = self.get(message_url).json()
        self.assertEqual(r["queue"], "testqueue")
        self.assertIn("payload", r)
        self.assertIn("Hello", r["payload"])

        # get all the messages for the player
        r = self.get(messages_url).json()['data']
        self.assertIn("testqueue", r)
        self.assertEqual(len(r["testqueue"]), 1)
        self.assertIn("payload", r["testqueue"][0])
        self.assertIn("Hello", r["testqueue"][0]["payload"])

        # get all the messages for the player again and make sure we're receiving the same thing
        self.assertEqual(self.get(messages_url).json()['data'], r)

        # get the messages and this time clear them as well
        r = self.get(messages_url + "?delete=true").json()['data']
        self.assertIn("testqueue", r)
        self.assertEqual(len(r["testqueue"]), 1)
        self.assertIn("payload", r["testqueue"][0])
        self.assertIn("Hello", r["testqueue"][0]["payload"])

    def test_messages_rows(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}

        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        first_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)
        second_message_id = r.json()["message_id"]
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)

        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all messages
        r = self.get(messages_url)
        js = r.json()['data']
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 2)
        self.assertEqual(len(js[otherqueue]), 2)

        # get 1 row and verify that it is the first one
        r = self.get(messages_url + "?rows=1")
        js = r.json()['data']
        self.assertEqual(len(js), 1)
        self.assertNotIn(otherqueue, js)
        self.assertEqual(len(js[queue]), 1)
        self.assertEqual(js[queue][0]["message_id"], first_message_id)

        # get 2 rows and verify that we have one from each queue
        r = self.get(messages_url + "?rows=2")
        js = r.json()['data']
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 1)
        self.assertEqual(js[queue][0]["message_id"], first_message_id)
        self.assertEqual(len(js[otherqueue]), 1)
        self.assertEqual(js[otherqueue][0]["message_id"], second_message_id)

    def test_messages_after(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        before_end_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)
        last_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get only the top row and verify that it is correct, each time
        for i in range(0, 2):
            r = self.get(messages_url + "?messages_after=%s" % before_end_message_id)
            js = r.json()['data']
            # Check we got one queue
            self.assertEqual(len(js), 1)
            # Check we got one message in the queue
            self.assertEqual(len(js[otherqueue]), 1)
            record = js[otherqueue][0]
            self.assertEqual(record["message_id"], last_message_id)
            self.assertEqual(record["payload"], otherdata["message"])

        # if we get by a larger number we should get nothing
        r = self.get(messages_url + "?messages_after=%s" % last_message_id)
        js = r.json()['data']
        self.assertEqual(js, {})

        # if we get by zero we should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url + "?messages_after=%s" % '0')
        js = r.json()['data']
        self.assertEqual(js, {})

        # if we get without a message number should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url)
        js = r.json()['data']
        self.assertEqual(js, {})

        # Send additional messages
        player_sender = self.make_player()

        # Post additional messages
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)
        before_end_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.CREATED)
        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get by zero should now return the two messages sent since last time
        r = self.get(messages_url + "?messages_after=%s" % (0))
        js = r.json()['data']
        self.assertEqual(len(js), 1)
        self.assertEqual(len(js[otherqueue]), 2)
        # Messages are returned oldest first
        self.assertEqual(js[otherqueue][0]["message_id"], before_end_message_id)
        self.assertEqual(js[otherqueue][1]["message_id"], top_message_id)

    def test_messages_multiplequeues(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        player_sender = self.make_player()
        num_queues = 5
        num_messages_per_queue = 3
        for i in range(num_queues):
            messagequeue_url = messagequeue_url_template.format(queue="testqueue-%s" % i)
            for j in range(num_messages_per_queue):
                data = {"message": {"Hello": "World", "queuenumber": i, "messagenumber": j}}
                r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the queues and delete them
        r = self.get(messages_url).json()['data']

        self.assertEqual(len(r), num_queues)
        for queue, messages in r.items():
            self.assertEqual(len(messages), num_messages_per_queue)

    def test_messages_longpoll(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.CREATED)
        message_url = r.json()["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the messages for the player using a 1 second long poll
        r = self.get(messages_url + "?timeout=1")
        self.assertIn("testqueue", r.json())
        self.assertEqual(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])

    def test_message_id(self):
        self.assertEqual("0-1", _next_message_id("0"))
        self.assertEqual("54-1", _next_message_id("54"))
        self.assertEqual("0-1", _next_message_id("0-0"))
        self.assertEqual("0-541", _next_message_id("0-540"))
        self.assertEqual("12345-1", _next_message_id("12345-0"))
