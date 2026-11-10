"""
Timestamps on the wire must keep the legacy format `YYYY-MM-DDTHH:MM:SS.ffffff[Z]`: no offset, always six
fractional digits. Existing clients cannot parse anything else.
"""
import datetime
import http.client as http_client
import re
import unittest

from drift.timeutil import format_utc_z
from driftbase.utils.test_utils import BaseCloudkitTest
from driftbase.utils.timeutil import parse_utc

WIRE_FORMAT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z?$")
LOOKS_LIKE_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")


def find_timestamps(value, path="$"):
    """Yield (path, string) for every timestamp-like string in a decoded JSON document."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from find_timestamps(v, f"{path}.{k}")
            if isinstance(k, str) and LOOKS_LIKE_TIMESTAMP.match(k):  # counters use timestamps as keys
                yield f"{path}.<key>", k
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from find_timestamps(v, f"{path}[{i}]")
    elif isinstance(value, str) and LOOKS_LIKE_TIMESTAMP.match(value):
        yield path, value


class WireFormatTestMixin:
    def assert_wire_format(self, document, min_count=1):
        found = list(find_timestamps(document))
        self.assertGreaterEqual(len(found), min_count, f"expected timestamps in response: {document}")
        for path, value in found:
            self.assertRegex(value, WIRE_FORMAT, f"{path} has a non-legacy timestamp format")
        return found


class ClientTimestampParserTest(unittest.TestCase):
    def test_accepts_iso_forms_and_returns_aware_utc(self):
        expected = datetime.datetime(2026, 11, 10, 9, 15, 0, 123456, tzinfo=datetime.UTC)
        for text in (
                "2026-11-10T09:15:00.123456",
                "2026-11-10T09:15:00.123456Z",
                "2026-11-10T09:15:00.123456+00:00",
                "2026-11-10T11:15:00.123456+02:00",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_utc(text), expected)

    def test_falls_back_to_lenient_formats(self):
        self.assertEqual(parse_utc("2026-11-10 09:15"), datetime.datetime(2026, 11, 10, 9, 15, tzinfo=datetime.UTC))
        self.assertEqual(parse_utc("Nov 10 2026 9:15AM"), datetime.datetime(2026, 11, 10, 9, 15, tzinfo=datetime.UTC))


class EndpointTimeFormatTest(WireFormatTestMixin, BaseCloudkitTest):
    """Every endpoint family that returns timestamps must use the wire format."""

    def test_user_and_player(self):
        self.auth()
        self.assert_wire_format(self.get(self.endpoints["my_user"]).json(), min_count=3)
        self.assert_wire_format(self.get(self.endpoints["my_player"]).json(), min_count=3)

    def test_players_list(self):
        self.auth()
        self.assert_wire_format(self.get(self.endpoints["players"]).json())

    def test_clients(self):
        self.auth()
        data = {"client_type": "t", "build": "b", "platform_type": "p", "app_guid": "g", "version": "v"}
        created = self.post(self.endpoints["clients"], data=data, expected_status_code=http_client.CREATED).json()
        self.assert_wire_format(created, min_count=0)
        self.headers["Authorization"] = "JTI %s" % created["jti"]
        self.assert_wire_format(self.get(self.endpoints["clients"]).json())
        self.assert_wire_format(self.put(created["url"]).json())  # heartbeat

    def test_messages(self):
        self.make_player()
        player_url = self.endpoints["my_player"]
        player = self.get(player_url).json()
        queue_url = player["messagequeue_url"].replace("%7Bqueue%7D", "{queue}").format(queue="testqueue")
        self.post(queue_url, data={"message": {"hello": "world"}}, expected_status_code=http_client.OK)
        messages = self.get(self.endpoints["my_messages"]).json()
        found = self.assert_wire_format(messages, min_count=2)
        self.assertTrue(all(value.endswith("Z") for _, value in found), "message timestamps carry a 'Z'")

    def test_counters(self):
        self.make_player()
        counters_url = self.get(self.endpoints["my_player"]).json()["counter_url"]
        timestamp = format_utc_z(datetime.datetime.now(datetime.UTC))
        self.patch(counters_url, data=[{"name": "timeformat", "value": 1, "timestamp": timestamp,
                                        "counter_type": "count"}])
        counters = self.get(counters_url).json()
        self.assertTrue(counters)
        self.assert_wire_format(self.get(self.get(self.endpoints["my_player"]).json()["countertotals_url"]).json(),
                                min_count=0)


class ServiceEndpointTimeFormatTest(WireFormatTestMixin, BaseCloudkitTest):
    def test_machines_and_servers(self):
        self.auth_service()
        machine = self._create_machine()
        self.assert_wire_format(machine)
        server = self._create_server(machine["machine_id"])
        server = self.get(f"/servers/{server['server_id']}").json()
        self.assert_wire_format(server)
        self.assert_wire_format(self.put(server["heartbeat_url"]).json())
        self.assert_wire_format(self.put(machine["url"]).json())

    def test_matches(self):
        self.auth_service()
        match = self._create_match()
        self.assert_wire_format(match)
        self.assert_wire_format(self.get("/matches").json())
        self.assert_wire_format(self.get("/matches", params={"use_pagination": True}).json())


class MatchesPaginationTest(BaseCloudkitTest):
    def test_out_of_range_page_is_404(self):
        self.auth_service()
        self.get("/matches", params={"use_pagination": True, "page": 0}, expected_status_code=http_client.NOT_FOUND)
        self.get("/matches", params={"use_pagination": True, "page": 99999},
                 expected_status_code=http_client.NOT_FOUND)

    def test_page_is_integer(self):
        self.auth_service()
        resp = self.get("/matches", params={"use_pagination": True, "page": 1}).json()
        self.assertIsInstance(resp["page"], int)
