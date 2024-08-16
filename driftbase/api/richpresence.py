from flask.views import MethodView
from marshmallow import Schema, fields
from drift.blueprint import Blueprint, abort
import http.client as http_client
from driftbase.models.db import Match, MatchPlayer, Client
from sqlalchemy.exc import NoResultFound
from drift.core.extensions.urlregistry import Endpoints
from flask import g, url_for
import logging


bp = Blueprint("richpresence", __name__, url_prefix="/players/<int:player_id>")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)
    
class RichPresenceRequestSchema(Schema):
    name = fields.List(fields.String())

class RichPresenceResponseSchema(Schema):
    game_mode = fields.Str()
    map_name = fields.Str()
    is_online = fields.Bool()
    is_in_game = fields.Bool()

class PlayerRichPresence:
    """
    Rich presence information for a particular player.
    @see PlayerRichPresenceSchema
    """
    
    game_mode = ""
    map_name = ""
    is_online = False
    is_in_game = False

    def __init__(self, player_id: int):
        client : Client|None = g.db.query(MatchPlayer) \
            .filter(Client.player_id == player_id) \
            .first()
        
        self.is_online = client.is_online if client else False
                    
        match_player : MatchPlayer|None = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.player_id == player_id) \
            .first()
        
        if not match_player: return
        
        match : Match|None = g.db.query(Match) \
            .filter(Match.match_id == match_player.match_id) \
            .one()

        if not match: return

        self.is_in_game = match_player.status == "active"
        self.game_mode = match.game_mode
        self.map_name = match.map_name
    
@bp.route('/rich-presence', endpoint='entry')
class RichPresenceAPI(MethodView):
    @bp.response(http_client.OK, RichPresenceResponseSchema)
    def get(self, player_id : int):
        """
        Single Player

        Retrieve rich-presence information for a specific player
        """
                
        return PlayerRichPresence(player_id)
    
@endpoints.register
def endpoint_info(*args):
    url = url_for(
        "richpresence.entry",
        player_id=1337,
        _external=True,
    ).replace('1337', '{player_id}')

    return {
        "template_richpresence": url
    }
