import gzip
import http.client as http_client
import json
import logging
from json import JSONDecodeError

from flask import request, url_for, jsonify, current_app
from flask.views import MethodView

from drift.blueprint import Blueprint, abort

from drift.core.extensions.driftconfig import get_feature_switch, get_tenant_config_value
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

from driftbase.utils import verify_log_request

log = logging.getLogger(__name__)
bp = Blueprint("events", __name__, url_prefix="/events")
endpoints = Endpoints()

clientlogger = logging.getLogger("clientlog")
eventlogger = logging.getLogger("eventlog")


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


@bp.route("", endpoint="list")
class EventsAPI(MethodView):
    def post(self):
        """
        Create event

        Public endpoint, called from the client and other services to log an
        event into eventlog
        Used to document action flow such as authentication, client exit,
        battle enter, etc.

        Example usage:

        POST http://localhost:10080/events

        [{"event_name": "my_event", "timestamp": "2015-01-01T10:00:00.000Z"}]

        """
        required_keys = ["event_name", "timestamp"]

        if request.headers.get('Content-Encoding', '') == 'gzip':
            try:
                data = gzip.decompress(request.data)
                events = json.loads(data)
            except JSONDecodeError as e:
                log.info(f"failed to decode compressed event data: {e.msg}")
                abort(http_client.BAD_REQUEST, "failed to decode compressed event data")
        else:
            events = request.json

        verify_log_request(events, required_keys)

        # The event log API should enforce the player_id to the current player, unless
        # the user has role "service" in which case it should only set the player_id if
        # it's not passed in the event.
        player_id = current_user.get("player_id", "")
        is_service = "service" in current_user["roles"] or "game_service" in current_user["roles"]

        for event in events:
            if is_service:
                event.setdefault("player_id", player_id)
            else:
                event["player_id"] = player_id  # Always override!
            eventlogger.info("eventlog", extra={"extra": event})

        if get_feature_switch('enable_eventlog_shoutout_forwarding') and is_service:
            events_to_shoutout = [event for event in events if not event.get('event_name', '').startswith('drift.')]
            if events_to_shoutout:
                batch_size = get_tenant_config_value('eventlog', 'max_batch_size',
                                                     defaults=dict(eventlog=dict(max_batch_size=5)))
                shoutout = current_app.extensions.get('shoutout').message
                if not batch_size:
                    shoutout("eventlog:events", events=events_to_shoutout)
                else:
                    for i in range(0, len(events_to_shoutout), batch_size):
                        shoutout("eventlog:events", events=events_to_shoutout[i: i + batch_size])

        if request.headers.get("Accept") == "application/json":
            return jsonify(status="OK"), http_client.CREATED
        else:
            return "OK", http_client.CREATED


@endpoints.register
def endpoint_info(*args):
    return {"eventlogs": url_for("events.list", _external=True)}
