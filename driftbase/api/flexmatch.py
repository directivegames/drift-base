"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

from flask_smorest import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for

from drift.core.extensions.jwt import current_user
from driftbase.flexmatch import get_player_latency_averages, update_player_latency, upsert_flexmatch_search
from six.moves import http_client

bp = Blueprint("flexmatch", "flexmatch", url_prefix="/flexmatch", description="Orchestration of GameLift/FlexMatch matchmaking")
endpoints = Endpoints()

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)

class FlexMatchPatchArgs(Schema):
    latency_ms = fields.Float(description="Latency between client and whatever server he uses for measurement.")
    region = fields.String(description="Which region the latency was measured against.")

@bp.route("/")
class FlexMatchAPI(MethodView):

    @bp.arguments(FlexMatchPatchArgs)
    def patch(self, args):
        # FIXME: define and use proper response schema
        player_id = current_user["player_id"]
        latency = args.get("latency_ms")
        region = args.get("region")
        if latency is None or region is None:
            abort(http_client.BAD_REQUEST) # FIXME: more descriptive error
        update_player_latency(player_id, region, latency)
        return {"latency_avg": get_player_latency_averages(player_id)}

    def post(self):
        ticket = upsert_flexmatch_search(current_user["player_id"])
        return http_client.OK


@endpoints.register
def endpoint_info(*args):
    return {"flexmatch": url_for("flexmatch.FlexMatchAPI", _external=True)}

