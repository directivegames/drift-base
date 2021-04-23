"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

from flask_smorest import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for
from six.moves import http_client
from drift.core.extensions.jwt import current_user
from driftbase import flexmatch
import logging


bp = Blueprint("matchmaking", "matchmaking", url_prefix="/matchmaking", description="Orchestration of matchmaking.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class MatchmakingPatchArgs(Schema):
    latency_ms = fields.Float(required=True, description="Latency between client and the region he's measuring against.")
    region = fields.String(required=True, description="Which region the latency was measured against.")

class MatchmakingPostArgs(Schema):
    matchmaker = fields.String(required=True, description="Which matchmaker (configuration name) to issue the ticket for. ")

@bp.route("/")
class MatchmakingAPI(MethodView):

    @bp.arguments(MatchmakingPatchArgs)
    def patch(self, args):
        """
        Add a freshly measured latency value to the player tally.
        Returns a region->avg_latency mapping.
        """
        player_id = current_user["player_id"]
        latency = args.get("latency_ms")
        region = args.get("region")
        if None in (latency, region) or region not in flexmatch.VALID_REGIONS or not isinstance(latency, (int, float)):
            abort(http_client.BAD_REQUEST, message="Invalid or missing arguments")
        flexmatch.update_player_latency(player_id, region, latency)
        return flexmatch.get_player_latency_averages(player_id), http_client.OK

    @bp.arguments(MatchmakingPostArgs)
    def post(self, args):
        """
        Insert a matchmaking ticket for the requesting player or his party.
        Returns a ticket.
        """
        try:
            ticket = flexmatch.upsert_flexmatch_ticket(current_user["player_id"], args.get("matchmaker"))
            return ticket, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error(f"Inserting/updating matchmaking ticket for player {current_user['player_id']} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

    def get(self):
        """
        Retrieve the active matchmaking ticket for the requesting player or his party, or empty dict if no such thing is found.
        """
        ticket = flexmatch.get_player_ticket(current_user["player_id"])
        return ticket or {}, http_client.OK

    def delete(self):
        """
        Delete the currently active matchmaking ticket for the requesting player or his party.
        """
        try:
            deleted_ticket = flexmatch.cancel_player_ticket(current_user["player_id"])
            if deleted_ticket is None:
                return {}, http_client.NOT_FOUND
            return {}, http_client.NO_CONTENT
        except flexmatch.GameliftClientException as e:
            log.error(f"Cancelling matchmaking ticket for player {current_user['player_id']} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

@endpoints.register
def endpoint_info(*args):
    return {"matchmaking": url_for("matchmaking.MatchmakingAPI", _external=True)}

