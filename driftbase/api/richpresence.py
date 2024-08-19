"""
Rich Presence is player metadata which is relevant to others, such as a players online status. Rich presence
can be queried from this extension, or you can listen to the message queue to get live updates without polling.

Messages will be available under 'players/<id>/richpresence/', and are automatically scoped to your friends list.
"""

from flask.views import MethodView
from marshmallow import Schema, fields
from drift.blueprint import Blueprint
import http.client as http_client
from driftbase.models.db import Match, MatchPlayer, Client
from driftbase.richpresence import RichPresenceSchema, PlayerRichPresence, get_richpresence
from drift.core.extensions.urlregistry import Endpoints
from flask import url_for
from driftbase.flask.flaskproxy import g

bp = Blueprint("richpresence", __name__, url_prefix="/rich-presence/")
endpoints = Endpoints()

def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)

class RichPresenceRequestSchema(Schema):
    name = fields.List(fields.String())

class RichPresenceListArgs(Schema):
    class Meta:
        strict = True

    player_id = fields.List(
        fields.Integer(), metadata=dict(description="Player ID's to filter for"
    ))

@bp.route('/<int:player_id>', endpoint='entry')
class RichPresenceAPI(MethodView):
    @bp.response(http_client.OK, RichPresenceSchema)
    def get(self, player_id : int):
        """
        Single Player

        Retrieve rich-presence information for a specific player
        """

        return get_richpresence(player_id)
    
# @bp.route('/', endpoint = 'list')
# class RichPresenceListAPI(MethodView):
#     @bp.arguments(RichPresenceListArgs, location='query')
#     @bp.response(http_client.OK, RichPresenceSchema(many=True))
#     def get(self, args : RichPresenceListArgs):
#         # TODO:

#         return []


@endpoints.register
def endpoint_info(*args):
    url = url_for(
        "richpresence.entry",
        player_id=1337,
        _external=True,
    ).replace('1337', '{player_id}')

    return {
        "template_richpresence": url,
        # "richpresence": url_for("richpresence.list")
    }