
import boto3
import random
import sys
import time
import logging

import json
from flask import g
from driftbase.parties import get_player_party, get_party_members
from driftbase.api.messages import _add_message


NUM_VALUES_FOR_LATENCY_AVERAGE = 3
REDIS_TTL = 1800

# FIXME: Figure out how to do multi-region matchmaking; afaik, the configuration isn't region based, but the queue it
#  uses (if using queues) is per region, and the queues themselves can have destination fleets in multiple regions.
#  To add to confusion, you can specify a configuration WITH_QUEUE and not specify any queue at all and that's a valid
#  configuration
AWS_REGION = "eu-west-1"

log = logging.getLogger(__name__)

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
        region: int( sum(float(l) for l in latencies) / min(NUM_VALUES_FOR_LATENCY_AVERAGE, len(latencies)) ) # FIXME: default value if no values have been reported?
        for region, latencies in zip(regions, results)
    }


###  Matchmaking  ###

def upsert_flexmatch_ticket(player_id, matchmaking_configuration):
    with _LockedTicketKey(_get_player_ticket_key(player_id)) as matchmaker:
        # Generate a list of players relevant to the request; this is the list of online players in the party if the player belongs to one, otherwise the list is just the player
        player_party_id = get_player_party(player_id)
        if player_party_id:
            member_ids = get_party_members(player_party_id)
        else:
            member_ids = [player_id]

        if matchmaker.ticket: # Existing ticket found
            # TODO: Check if I need to add this player to the ticket.
            return matchmaker.ticket

        gamelift_client = boto3.client("gamelift", region_name=AWS_REGION) # FIXME: How do I deal with aws credentials ?
        response = gamelift_client.start_matchmaking(
            ConfigurationName = matchmaking_configuration,
            Players = [
                {
                    "PlayerId": str(member_id),
                    "PlayerAttributes": _get_player_attributes(member_id),
                    "LatencyInMs": get_player_latency_averages(member_id)
                }
                for member_id in member_ids
            ],
        )
        if "MatchmakingTicket" not in response:
            raise GameliftClientException("Unable to start matchmaking", response)

        # FIXME: finalize and encapsulate redis object format for storage, currently just storing the ticket as is.
        matchmaker.ticket = response["MatchmakingTicket"]

        _post_matchmaking_event_to_members(member_ids, "StartedMatchMaking")
        return matchmaker.ticket

def get_player_ticket(player_id):
    return g.redis.conn.hgetall(_get_player_ticket_key(player_id))


## Helpers ##

def _get_player_regions(player_id):
    """ Return a list of regions for whom 'player_id' has reported latency values. """
    return [e.decode("ascii").split(':')[-1] for e in g.redis.conn.keys(_get_player_latency_key(player_id) + '*')]

def _get_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")

def _get_player_ticket_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return g.redis.make_key(f"party:{player_party_id}:flexmatch:")
    return g.redis.make_key(f"player:{player_id}:flexmatch:")

def _get_player_attributes(player_id):
    #FIXME: Placeholder for extra matchmaking attribute gathering per player
    return {"skill": {"N": 50}}

def _post_matchmaking_event_to_members(receiving_player_ids, event, expiry=30):
    """ Insert a event into the 'matchmaking' queue of the 'players' exchange. """
    if not receiving_player_ids:
        log.warning(f"Empty receiver in matchmaking event {event} message")
        return
    if not isinstance(receiving_player_ids, (set, list)):
        receiving_player_ids = [receiving_player_ids]
    payload = {"event": event}
    for receiver_id in receiving_player_ids:
        _add_message("players", receiver_id, "matchmaking", payload, expiry)


class _LockedTicketKey(object):
    """
    Context manager for synchronizing creation and modification of matchmaking tickets.
    """
    MAX_LOCK_TIME_SECONDS = 30 # Avoid stale locking by defining a maximum time a lock can be held. This is probably excessive though...

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
            # Attempt to acquire the lock by setting a value on the key to something unique to this request.
            # Fails if the key already exists, meaning someone else is holding the lock
            if self._redis.conn.set(self._lock_key, self._lock_sentinel_value, nx=True, ex=self.MAX_LOCK_TIME_SECONDS):
                # we hold the lock now
                ticket = self._redis.conn.get(self._key)
                if ticket is not None:
                    self._ticket = json.loads(ticket)
                return self
            else: # someone else holds the lock for this key
                time.sleep(0.1) # Kind of miss stackless channels for 'block-until-woken' :)

    def __exit__(self, exc_type, exc_val, exc_tb):
        lock_sentinel_value = int(self._redis.conn.get(self._lock_key) or 0) # or 0 in case we expired and someone else deleted the key
        if lock_sentinel_value != self._lock_sentinel_value:
            # If the sentinel value differs, we held the lock for too long and someone else is now holding the lock,
            # so we'll bail without updating anything
            return
        with self._redis.conn.pipeline() as pipe:
            if exc_type is None and self._modified is True:
                pipe.delete(self._key) # Always update the ticket wholesale, i.e. don't leave stale fields behind.
                pipe.set(self._key, json.dumps(self._ticket))
            pipe.delete(self._lock_key) # Release the lock
            pipe.execute()


class GameliftClientException(Exception):
    def __init__(self, user_message, debug_info):
        super().__init__(user_message, debug_info)
        self.msg = user_message
        self.debugs = debug_info