import logging
from dateutil import parser

import http.client as http_client

from flask import g, url_for
from drift.blueprint import abort

from driftbase.models.db import MatchEvent
log = logging.getLogger(__name__)

EXPIRE_SECONDS = 86400


def log_match_event(match_id, player_id, event_type_name, details=None, db_session=None):

    if not db_session:
        db_session = g.db

    log.info("Logging player event to DB: player_id=%s, event=%s", player_id, event_type_name)
    event = MatchEvent(event_type_id=None,
                       event_type_name=event_type_name,
                       player_id=player_id,
                       match_id=match_id,
                       details=details)
    db_session.add(event)
    db_session.commit()


def verify_log_request(events, required_keys=None):
    if not isinstance(events, list):
        abort(http_client.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
    if not events:
        log.warning("Invalid log request. No loglines.")
        abort(http_client.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
    for event in events:
        if not isinstance(event, dict):
            log.warning("Invalid log request. Entry not dict: %s", event)
            abort(http_client.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
        if required_keys:
            for key in required_keys:
                if key not in event:
                    log.warning("Invalid log request. Missing required key '%s' from %s",
                                key, event)
                    abort(http_client.METHOD_NOT_ALLOWED,
                          message="Required key, '%s' missing from event" % key)
        if "timestamp" in event:
            try:
                parser.parse(event["timestamp"])
            except ValueError:
                log.warning("Invalid log request. Timestamp %s could not be parsed for %s",
                            event["timestamp"], event)
                abort(http_client.METHOD_NOT_ALLOWED, message="Invalid timestamp, '%s' in event '%s'" %
                      (event["timestamp"], event["event_name"]))


def url_user(user_id):
    return url_for("users.entry", user_id=user_id, _external=True)


def url_player(player_id):
    return url_for("players.entry", player_id=player_id, _external=True)


def url_client(client_id):
    return url_for("clients.entry", client_id=client_id, _external=True)
