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


bp = Blueprint("flexmatch", "flexmatch", url_prefix="/flexmatch", description="Orchestration of GameLift/FlexMatch matchmaking")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class FlexMatchPatchArgs(Schema):
    latency_ms = fields.Float(required=True, description="Latency between client and the region he's measuring against.")
    region = fields.String(required=True, description="Which region the latency was measured against.")

class FlexMatchPostArgs(Schema):
    matchmaker = fields.String(required=True, description="Which matchmaker (configuration name) to issue the ticket for. ")

@bp.route("/")
class FlexMatchAPI(MethodView):

    VALID_REGIONS = {"eu-west-1"}

    @bp.arguments(FlexMatchPatchArgs)
    def patch(self, args):
        """
        Add a freshly measured latency value to the player tally.
        Returns a region->avg_latency mapping.
        """
        player_id = current_user["player_id"]
        latency = args.get("latency_ms")
        region = args.get("region")
        if None in (latency, region) or region not in self.VALID_REGIONS or not isinstance(latency, (int, float)):
            abort(http_client.BAD_REQUEST) # FIXME: more descriptive error would be nice
        flexmatch.update_player_latency(player_id, region, latency)
        return flexmatch.get_player_latency_averages(player_id), http_client.OK

    @bp.arguments(FlexMatchPostArgs)
    def post(self, args):
        """
        Insert a matchmaking ticket for the requesting player or his party.
        Returns a region->avg_latency mapping.
        """
        try:
            ticket = flexmatch.upsert_flexmatch_ticket(current_user["player_id"], args.get("matchmaker"))
            return ticket, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error("Inserting/updating matchmaking ticket for player {player} failed: Gamelift response:\n{response}".format(player=current_user["player_id"], response=str(e.debugs)))
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

    def get(self):
        """
        Retrieve the active matchmaking ticket for the requesting player or his party, or empty dict if no such thing is found.
        """
        ticket = flexmatch.get_player_ticket(current_user["player_id"])
        return ticket or {}, http_client.OK

@endpoints.register
def endpoint_info(*args):
    return {"flexmatch": url_for("flexmatch.FlexMatchAPI", _external=True)}

