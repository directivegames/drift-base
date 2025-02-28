import datetime
import gzip
import http.client as http_client
import json
import mock

from drift.core.extensions.jwt import current_user
from driftbase.systesthelper import DriftBaseTestCase


class EventsTest(DriftBaseTestCase):
    """
    Tests for the /events and /clientlogs endpoint
    """

    def test_events(self):
        self.auth()
        self.assertIn("eventlogs", self.endpoints)
        endpoint = self.endpoints["eventlogs"]
        r = self.post(
            endpoint,
            data=[{"hello": "world"}],
            expected_status_code=http_client.METHOD_NOT_ALLOWED,
        )
        self.assertIn("'event_name'", r.json()["error"]["description"])

        self.post(endpoint, expected_status_code=http_client.UNSUPPORTED_MEDIA_TYPE)
        self.post(
            endpoint, data=[], expected_status_code=http_client.METHOD_NOT_ALLOWED
        )
        self.post(
            endpoint, data=["test"], expected_status_code=http_client.METHOD_NOT_ALLOWED
        )

        r = self.post(
            endpoint,
            data=[{"hello": "world", "event_name": "dummy"}],
            expected_status_code=http_client.METHOD_NOT_ALLOWED,
        )
        self.assertIn("'timestamp'", r.json()["error"]["description"])

        r = self.post(
            endpoint,
            data=[{"hello": "world", "event_name": "dummy", "timestamp": "dummy"}],
            expected_status_code=http_client.METHOD_NOT_ALLOWED,
        )
        self.assertIn("Invalid timestamp", r.json()["error"]["description"])

        ts = datetime.datetime.utcnow().isoformat() + "Z"
        r = self.post(
            endpoint,
            data=[{"hello": "world", "event_name": "dummy", "timestamp": ts}],
            expected_status_code=http_client.CREATED,
        )

    def test_compressed_events(self):
        self.auth()
        self.assertIn("eventlogs", self.endpoints)
        endpoint = self.endpoints["eventlogs"]
        ts = datetime.datetime.utcnow().isoformat() + "Z"
        r = self.post(
            endpoint,
            data=gzip.compress(json.dumps([{"hello": "world", "event_name": "dummy", "timestamp": ts}]).encode('utf-8')),
            headers={'Content-Encoding': 'gzip'},
            expected_status_code=http_client.CREATED,
        )

    def test_events_from_server(self):
        # The event log API should enforce the player_id to the current player, unless
        # the user has role "service" in which case it should only set the player_id if
        # it's not passed in the event.

        def eventlog(message, extra):
            expect_player_id = self.expect_player_id or current_user["player_id"]
            self.assertEqual(extra["extra"]["player_id"], expect_player_id)

        with mock.patch("driftbase.api.events.eventlogger.info", eventlog):
            self.auth()
            endpoint = self.endpoints["eventlogs"]
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            event = {"event_name": "dummy", "timestamp": ts, "message": "a message"}

            # Ommitting player_id, it should be pulled from current_user
            self.expect_player_id = None  # Expect value from current_user
            self.post(endpoint, data=[event], expected_status_code=http_client.CREATED)

            # Set player_id to 88888, but it should be ignored as we don't have role 'service'.
            event["player_id"] = 88888
            self.expect_player_id = None  # Expect value from current_user
            self.post(endpoint, data=[event], expected_status_code=http_client.CREATED)

            # Set player_id to 88888 and runs with role 'service'.
            self.auth_service()
            event["player_id"] = 88888
            self.expect_player_id = 88888
            self.post(endpoint, data=[event], expected_status_code=http_client.CREATED)

    def test_clientlogs(self):
        self.auth()
        self.assertIn("clientlogs", self.endpoints)
        endpoint = self.endpoints["clientlogs"]
        self.post(endpoint, expected_status_code=http_client.UNSUPPORTED_MEDIA_TYPE)
        self.post(
            endpoint, data=[], expected_status_code=http_client.METHOD_NOT_ALLOWED
        )
        self.post(
            endpoint, data=["test"], expected_status_code=http_client.METHOD_NOT_ALLOWED
        )

        # Using a LogRecord keyword like 'message' should not fail:
        self.post(
            endpoint,
            data=[{"hello": "world", "message": "a message"}],
            expected_status_code=http_client.CREATED,
        )

        # if we do pass an auth header field it must be valid...
        self.headers["Authorization"] = self.headers["Authorization"] + "_"
        self.post(
            endpoint,
            data=[{"hello": "world"}],
            expected_status_code=http_client.UNAUTHORIZED,
        )

        # but the auth field isn't required
        del self.headers["Authorization"]
        self.post(
            endpoint,
            data=[{"hello": "world"}],
            expected_status_code=http_client.CREATED,
        )
        
    
    
    def test_events_filter(self):
        self.auth()
        self.auth_service()
        self.assertIn("eventlogs", self.endpoints)
        endpoint = self.endpoints["eventlogs"]
        
        shoutout_mock = mock.Mock()
        ts = datetime.datetime.now().isoformat() + "Z"
        with mock.patch("driftbase.api.events._get_shoutout", return_value=shoutout_mock):
            with mock.patch("driftbase.api.events.get_feature_switch", return_value=True):
                # default block list
                self.post(
                    endpoint,
                    data=[{"hello": "world", "event_name": "drift.blah", "timestamp": ts}],
                    expected_status_code=http_client.CREATED,
                )
                shoutout_mock.message.assert_not_called()
                shoutout_mock.reset_mock()
                
                self.post(
                    endpoint,
                    data=[{"hello": "world", "event_name": "player.battle.damage_dealt", "timestamp": ts}],
                    expected_status_code=http_client.CREATED,
                )
                shoutout_mock.message.assert_called_once()
                shoutout_mock.reset_mock()
                
                # with block list
                with mock.patch(
                    "driftbase.api.events.default_eventlog_config",
                    dict(eventlog=dict(max_batch_size=5, shoutout_block_list=["drift.*", "player.battle.damage_dealt"])),
                ):
                    self.post(
                        endpoint,
                        data=[{"hello": "world", "event_name": "dummy", "timestamp": ts}],
                        expected_status_code=http_client.CREATED,
                    )
                    shoutout_mock.message.assert_called_once()
                    shoutout_mock.reset_mock()

                    self.post(
                        endpoint,
                        data=[{"hello": "world", "event_name": "drift.blah", "timestamp": ts}],
                        expected_status_code=http_client.CREATED,
                    )
                    shoutout_mock.message.assert_not_called()
                    shoutout_mock.reset_mock()
                    
                    self.post(
                        endpoint,
                        data=[{"hello": "world", "event_name": "drift.foo.bar", "timestamp": ts}],
                        expected_status_code=http_client.CREATED,
                    )
                    shoutout_mock.message.assert_not_called()
                    shoutout_mock.reset_mock()
                    
                    self.post(
                        endpoint,
                        data=[{"hello": "world", "event_name": "player.battle.damage_dealt", "timestamp": ts}],
                        expected_status_code=http_client.CREATED,
                    )
                    shoutout_mock.message.assert_not_called()
                    shoutout_mock.reset_mock()
                    
                    self.post(
                        endpoint,
                        data=[{"hello": "world", "event_name": "player.battle.damage_dealt.foo", "timestamp": ts}],
                        expected_status_code=http_client.CREATED,
                    )
                    shoutout_mock.message.assert_called_once()
                    shoutout_mock.reset_mock()
