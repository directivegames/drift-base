"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

from flask_smorest import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for

from drift.core.extensions.jwt import current_user
from driftbase.flexmatch import get_player_latency_average, update_player_latency, upsert_flexmatch_search
from six.moves import http_client

bp = Blueprint("flexmatch", "flexmatch", url_prefix="/flexmatch", description="Orchestration of GameLift/FlexMatch matchmaking")
endpoints = Endpoints()

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)

class FlexMatchPatchArgs(Schema):
    latency_ms = fields.Float(required=False, description="Latency between client and whatever server he uses for measurement as reported by client")

@bp.route("/")
class FlexMatchAPI(MethodView):

    def get(self):
        pass

    @bp.arguments(FlexMatchPatchArgs)
    def patch(self, args):
        # FIXME: define and use proper response schema
        player_id = current_user["player_id"]
        latency = args.get("latency_ms")
        if latency is None:
            abort(http_client.BAD_REQUEST) # FIXME:
        update_player_latency(player_id, latency)
        return {"latency_avg": get_player_latency_average(player_id)}

    def post(self):
        #ticket = upsert_flexmatch_search(current_user["player_id"])
        breakpoint()
        return {"ticket_id": upsert_flexmatch_search(current_user["player_id"])}


@endpoints.register
def endpoint_info(*args):
    return {"flexmatch": url_for("flexmatch.FlexMatchAPI", _external=True)}

