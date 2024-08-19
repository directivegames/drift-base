from __future__ import annotations
from driftbase.flask.flaskproxy import g
from marshmallow import Schema, fields
from marshmallow.decorators import post_load
from driftbase.messages import post_message
from driftbase.models.db import Friendship

class PlayerRichPresence:
    """
    Rich presence information for a particular player.
    @see PlayerRichPresenceSchema
    """
    
    game_mode = ""
    map_name = ""
    is_online = False
    is_in_game = False

    def __init__(self, is_online: bool = False, is_in_game: bool = False, game_mode: str = "", map_name: str = ""):
        self.is_online = is_online
        self.is_in_game = is_in_game
        self.map_name = map_name
        self.game_mode = game_mode

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False
    
class RichPresenceSchema(Schema):
    game_mode = fields.Str()
    map_name = fields.Str()
    is_online = fields.Bool()
    is_in_game = fields.Bool()

    @post_load
    def make_rich_presence(self, data, **kwargs):
        return PlayerRichPresence(**data)

def _get_friends(player_id) -> list[int]:
    """
    Returns an array of player_ids, matching your friends list.
    """

    left = g.db.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id, status="active")
    right = g.db.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id, status="active")
    friend_rows = left.union_all(right)

    return [row[2] for row in friend_rows]

def _get_redis_key(player_id) -> str:
    return g.redis.make_key(f"rich_presence:{player_id}")
    
def get_richpresence(player_id : int) -> PlayerRichPresence:
    """
    Fetches the rich presence information for the specified player.
    """

    key = _get_redis_key(player_id)
    presence_json = g.redis.get(key)

    if presence_json:
        return RichPresenceSchema(many=False).load(presence_json)
    else:
        return PlayerRichPresence()

def set_online_status(player_id: int, is_online: bool):
    """
    Sets the players online status, and updates rich-presence
    """
    presence = get_richpresence(player_id)
    presence.is_online = is_online
    set_richpresence(player_id, presence)

def set_match_status(player_id: int, map_name: str, game_mode: str, is_in_game : bool = True):
    """
    Sets the players match status, and updates rich-presence
    """
    presence = get_richpresence(player_id)
    presence.is_in_game = is_in_game
    presence.game_mode = game_mode
    presence.map_name = map_name
    set_richpresence(player_id, presence)

def clear_match_status(player_id : int) -> None:
    """
    Returns a players match status back to the default values
    """
    set_match_status(player_id, "", "", False)

def set_richpresence(player_id : int, presence : PlayerRichPresence) -> None:
    """
    Sets the rich presence information for a player. Will queue messages for consumption by interested
    clients.
    """

    presence_json = RichPresenceSchema(many=False).dump(presence)
    key = _get_redis_key(player_id)

    original_presence = g.redis.get(key)

    if original_presence != presence_json:
        for receiver_id in _get_friends(player_id):
            post_message("players", int(receiver_id), "richpresence", presence_json, sender_system=True)
    
    g.redis.set(key, presence_json)
