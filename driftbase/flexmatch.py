
import boto3
import random
import sys
import time
import logging
from flask import g
from driftbase.parties import get_player_party, get_party_members
from driftbase.api.messages import _add_message

NUM_VALUES_FOR_LATENCY_AVERAGE = 3
AWS_REGION = "eu-west-1"  #FIXME: Get from config or environment
MATCHMAKING_CONFIGURATION_NAME = "PerseusHilmarMatchmaker" #FIXME: Get from config, client or environment
REDIS_TTL = 1800

log = logging.getLogger(__name__)
#gamelift_client = boto3.client("gamelift", region_name=AWS_REGION)

# DEBUGS/TESTING
class MockGameLiftClient(object):
    def start_matchmaking(self, **kwargs):
        return {
            "MatchmakingTicket": {
                "TicketId": 123,
                "Status": "Searching"
            }
        }
gamelift_client = MockGameLiftClient()

### Latency report handling ###

def update_player_latency(player_id, region, latency_ms):
    region_key = _get_player_latency_key(player_id) + region
    g.redis.conn.lpush(region_key, latency_ms)
    if g.redis.conn.llen(region_key) > NUM_VALUES_FOR_LATENCY_AVERAGE:
        g.redis.conn.ltrim(region_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE-1)

def get_player_latency_averages(player_id):
    player_latency_key = _get_player_latency_key(player_id)
    regions = _get_player_regions(player_id)
    with g.redis.conn.pipeline() as pipe:
        for region in regions:
            pipe.lrange(player_latency_key + region, 0, NUM_VALUES_FOR_LATENCY_AVERAGE)
        results = pipe.execute()
    return {
        region: int( sum(float(l) for l in latencies) / min(NUM_VALUES_FOR_LATENCY_AVERAGE, len(latencies)) ) # FIXME: default value if no values reported?
        for region, latencies in zip(regions, results)
    }

def _get_player_regions(player_id):
    return [e.decode("ascii").split(':')[-1] for e in g.redis.conn.keys(_get_player_latency_key(player_id) + '*')]

def _get_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")

### Matchmaking  ###

def upsert_flexmatch_search(player_id, gl_client=None):
    client = gl_client if gl_client is not None else gamelift_client # Hack for testing
    matchmaking_key = _get_matchmaking_state_key(player_id)
    with _LockedMatchmaker(matchmaking_key) as matchmaker:
        if matchmaker.ticket: # Existing ticket found
            # FIXME: enumerate and handle all real ticket statuses?
            # FIXME: Check if I need to add this player to the ticket.
            return matchmaker.ticket

        # Generate a list of players relevant to the request; this is the list of online players in the party if the player belongs to one, otherwise the list is just the player
        player_party_id = get_player_party(player_id)
        if player_party_id:
            member_ids = get_party_members(player_party_id)
        else:
            member_ids = [player_id]
        breakpoint()
        response = client.start_matchmaking(
            ConfigurationName = MATCHMAKING_CONFIGURATION_NAME,
            Players = [
                {
                    "PlayerId": str(member_id),
                    "PlayerAttributes": {"skill": {"N": 50}},
                    "LatencyInMs": get_player_latency_averages(member_id) # FIXME: check if this is the intended mapping, i.e. look up the rule who consumes this
                }
                for member_id in member_ids
            ],
        )
        if "MatchmakingTicket" not in response:
            return {
                "error": "No 'MatchmakingTicket' in ticket response, this is weird",
                "response_for_debug": response,
            }

        # FIXME: finalize and encapsulate redis object format for storage, currently just storing the ticket as is.
        matchmaker.ticket = response["MatchmakingTicket"]

        # TODO: Generate matchmaking status messages for all players in member_ids
        _post_matchmaking_event_message_to_player(member_ids, "StartedMatchMaking")
        return matchmaker.ticket

def _get_matchmaking_state_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return g.redis.make_key("party:{}:flexmatch:".format(player_party_id))
    return g.redis.make_key("player:{}:flexmatch:".format(player_id))

def _get_matchmaking_status_for_player(player_id):
    return g.redis.conn.hgetall(_get_matchmaking_state_key(player_id))

def _post_matchmaking_event_message_to_player(receiving_player_ids, event, expiry=30):
    """ Insert a event into the 'matchmaking' queue of the 'players' exchange. """
    if not receiving_player_ids:
        log.warning(f"Empty receiver in matchmaking event {event} message")
        return
    if not isinstance(receiving_player_ids, (set, list)):
        receiving_player_ids = [receiving_player_ids]
    payload = {"event": event}
    for receiver_id in receiving_player_ids:
        _add_message("players", receiver_id, "matchmaking", payload, expiry)

class _LockedMatchmaker(object):
    """
    Context manager for synchronizing creation and modification of matchmaking tickets.
    """
    def __init__(self, key):
        self._key = key
        self._lock_key = key + 'LOCK'
        self._lock_sentinel_value = random.randint(0, sys.maxsize)
        self._redis = g.redis
        self._modified = False
        self._ticket = None

    @property
    def ticket(self):
        return self._ticket

    @ticket.setter
    def ticket(self, new_ticket):
        self._ticket = new_ticket
        self._modified = True

    def __enter__(self):
        while True:
            # Set key value if not exists to a random sentinel value with expiry of 3 seconds
            if self._redis.conn.set(self._lock_key, self._lock_sentinel_value, nx=True, ex=30):
                # we hold the lock
                self.ticket = self._redis.conn.hgetall(self._key)
                return self
            else: # someone else holds the lock for this key
                time.sleep(0.5) # We shou

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and self._modified is True:
            self._redis.conn.set(self._key, self._ticket)
        value = self._redis.conn.get(self._lock_key)
        if value == self._lock_sentinel_value:
            self._redis.conn.delete(self._lock_key)