
from flask import g

NUM_VALUES_FOR_LATENCY_AVERAGE = 3


def update_player_latency(player_id, latency_ms):
    redis = g.redis.conn
    latency_key = _make_player_latency_key(player_id)
    redis.lpush(latency_key, latency_ms)

def get_player_latency_average(player_id):
    latency_key = _make_player_latency_key(player_id)
    redis = g.redis.conn
    redis.ltrim(latency_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE - 1)  # only use the 5 latest value
    values = [float(i) for i in redis.lrange(latency_key, 0, -1)]
    return sum(values) / min(NUM_VALUES_FOR_LATENCY_AVERAGE, len(values))

def _make_player_latency_key(player_id):
    return g.redis.make_key("player:{}:latency:".format(player_id))