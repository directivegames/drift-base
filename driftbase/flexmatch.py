
import boto3
from flask import g
from driftbase.parties import get_player_party, get_party_members

NUM_VALUES_FOR_LATENCY_AVERAGE = 3
AWS_REGION = "eu-west-1"  #FIXME: Get from config or environment
MATCHMAKING_CONFIGURATION_NAME = "PerseusHilmarMatchmaker" #FIXME: Get from config or environment
REDIS_TTL = 1800

gamelift_client = boto3.client("gamelift", region_name=AWS_REGION)


def update_player_latency(player_id, region, latency_ms):
    region_key = _make_player_latency_key(player_id) + region
    g.redis.conn.lpush(region_key, latency_ms)
    if g.redis.conn.llen(region_key) > NUM_VALUES_FOR_LATENCY_AVERAGE:
        g.redis.conn.ltrim(region_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE-1)

def get_player_latency_averages(player_id):
    player_latency_key = _make_player_latency_key(player_id)
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
    return [e.decode("ascii").split(':')[-1] for e in g.redis.conn.keys(_make_player_latency_key(player_id) + '*')]

def _make_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")



def upsert_flexmatch_search(player_id):
    breakpoint()
    fm_state = _get_matchmaking_status_for_player(player_id)
    if fm_state:
        # FIXME: enumerate and handle all real ticket statuses
        if fm_state["status"] == "searching":
            return fm_state["ticket_id"]

    # Generate a list of players relevant to the request; this is the list of online players in the party if the player belongs to one, otherwise the list is just the player
    player_party_id = get_player_party(player_id)
    if player_party_id:
        member_ids = get_party_members(player_party_id)
    else:
        member_ids = [player_id]

    response = gamelift_client.start_matchmaking(
        ConfigurationName = MATCHMAKING_CONFIGURATION_NAME,
        Players = [
            {
                "PlayerId": str(member_id),
                "PlayerAttribute": {"skill": {"N": 50}},
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

    ticket = response["MatchmakingTicket"]
    ticket_id = ticket["TicketId"]
    ticket_status = ticket["Status"]
    fm_state = {
        "ticked_it": ticket_id,
        "status": ticket_status
    }
    g.redis.conn.set(_make_matchmaking_state_key(player_id), fm_state)

    # FIXME: Generate matchmaking status messages for all players in member_ids
    return {"ticket_id": ticket_id}




def _make_matchmaking_state_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return g.redis.make_key("party:{}:flexmatch:".format(player_party_id))
    return g.redis.make_key("player:{}:flexmatch:".format(player_id))

def _get_matchmaking_status_for_player(player_id):
    """
    Format of status:
    {
        "ticket_id" : <some id>
        "status" : <some status string?>
    """
    return g.redis.conn.hgetall(_make_matchmaking_state_key(player_id))