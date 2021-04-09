
import boto3
import random
import sys
import time
import logging
from flask import g
from driftbase.parties import get_player_party, get_party_members
from driftbase.resources.flexmatch import TIER_DEFAULTS
from driftbase.api.messages import _add_message


# FIXME: All of the below should preferably be configuration values instead of constants
NUM_VALUES_FOR_LATENCY_AVERAGE = 3
AWS_REGION = "eu-west-1"
REDIS_TTL = 1800

log = logging.getLogger(__name__)
gamelift_client = boto3.client("gamelift", region_name=AWS_REGION)

###  Latency reporting  ###

def update_player_latency(player_id, region, latency_ms):
    region_key = _get_player_latency_key(player_id) + region
    with g.redis.conn.pipeline() as pipe:
        pipe.lpush(region_key, latency_ms)
        pipe.ltrim(region_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE-1)
        pipe.execute()

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


###  Matchmaking  ###

def upsert_flexmatch_ticket(player_id):
    matchmaking_key = _get_player_ticket_key(player_id)
    with _LockedTicketKey(matchmaking_key) as matchmaker:
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

        response = client.start_matchmaking(
            ConfigurationName = _get_flexmatch_config_name(),
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
            raise GameliftClientException("Unable to start matchmaking", response)

        # FIXME: finalize and encapsulate redis object format for storage, currently just storing the ticket as is.
        matchmaker.ticket = response["MatchmakingTicket"]

        # TODO: Generate matchmaking status messages for all players in member_ids
        _post_matchmaking_event_message_to_player(member_ids, "StartedMatchMaking")
        return matchmaker.ticket

def get_player_ticket(player_id):
    return g.redis.conn.hgetall(_get_player_ticket_key(player_id))


## Helpers ##

def _get_player_regions(player_id):
    return [e.decode("ascii").split(':')[-1] for e in g.redis.conn.keys(_get_player_latency_key(player_id) + '*')]

def _get_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")

def _get_player_ticket_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return g.redis.make_key("party:{}:flexmatch:".format(player_party_id))
    return g.redis.make_key("player:{}:flexmatch:".format(player_id))

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

def _get_flexmatch_config_name():
    configuration_name = TIER_DEFAULTS['matchmaking_configuration_name']
    tenant = g.conf.tenant
    if not tenant:
        return configuration_name
    return tenant.get('flexmatch', {}).get('matchmaking_configuration_name', configuration_name)


class _LockedTicketKey(object):
    """
    Context manager for synchronizing creation and modification of matchmaking tickets.
    """
    MAX_WAIT_TIME_SECONDS = 30 # Avoid stale locking by defining a maximum time a lock can be held

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
            # Attempt to acquire the lock by setting a value on the key to a value unique to this request.
            # Fails if the key already exists, meaning someone else is holding the lock
            if self._redis.conn.set(self._lock_key, self._lock_sentinel_value, nx=True, ex=self.MAX_WAIT_TIME_SECONDS):
                # we hold the lock now
                self.ticket = self._redis.conn.hgetall(self._key)
                return self
            else: # someone else holds the lock for this key
                time.sleep(0.1) # Kind of miss stackless channels for 'block-until-woken' :)

    def __exit__(self, exc_type, exc_val, exc_tb):
        lock_sentinel_value = self._redis.conn.get(self._lock_key)
        if lock_sentinel_value != self._lock_sentinel_value:
            # If the sentinel value differs, we held the lock for too long and someone else is now holding the lock,
            # so we'll bail without updating anything
            return
        with self._redis.conn.pipeline() as pipe:
            if exc_type is None and self._modified is True:
                pipe.delete(self._key) # Always update the ticket wholesale, i.e. don't leave stale fields behind.
                pipe.hset(self._key, self._ticket)
            pipe.delete(self._lock_key) # Release the lock
            pipe.execute()


class GameliftClientException(Exception):
    def __init__(self, user_message, debug_info):  # real signature unknown
        self.msg = user_message
        self.debugs = debug_info