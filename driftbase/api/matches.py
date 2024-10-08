import datetime
import http.client as http_client
import logging
import marshmallow as ma
import json
from contextlib import ExitStack
from flask import url_for, g, jsonify, current_app
from flask.views import MethodView
from drift.blueprint import Blueprint, abort
from driftbase.richpresence import RichPresenceService

from drift.core.extensions.jwt import current_user, requires_roles
from drift.core.extensions.urlregistry import Endpoints
from sqlalchemy import func, cast, Integer, case, and_
from sqlalchemy.engine import Row

from driftbase.matchqueue import process_match_queue
from driftbase.models.db import Machine, Server, Match, MatchTeam, MatchPlayer, MatchQueuePlayer, CorePlayer
from driftbase.utils import log_match_event
from driftbase.utils import url_player

DEFAULT_ROWS = 100

log = logging.getLogger(__name__)

bp = Blueprint("matches", __name__, url_prefix="/matches")
endpoints = Endpoints()

MATCH_HEARTBEAT_TIMEOUT_SECONDS = 60


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


def utcnow():
    return datetime.datetime.utcnow()


class ActiveMatchesGetQuerySchema(ma.Schema):
    ref = ma.fields.String()
    placement = ma.fields.String()
    realm = ma.fields.String()
    version = ma.fields.String()
    player_id = ma.fields.List(ma.fields.Integer(), load_default=[])
    match_id = ma.fields.List(ma.fields.Integer(), load_default=[])
    rows = ma.fields.Integer(load_default=DEFAULT_ROWS)


@bp.route('/active', endpoint='active')
class ActiveMatchesAPI(MethodView):
    """UE4 matches available for matchmaking
    """

    @bp.arguments(ActiveMatchesGetQuerySchema, location='query')
    def get(self, args):
        """
        Get active matches

        This endpoint used by clients to fetch a list of matches available
        for joining
        """
        num_rows = args["rows"] or DEFAULT_ROWS

        query = g.db.query(Match, Server, Machine)
        query = query.filter(Server.machine_id == Machine.machine_id,
                             Match.server_id == Server.server_id,
                             Match.status.notin_(["ended", "completed"]),
                             Server.status.in_(["started", "running", "active", "ready"]),
                             Server.heartbeat_date >= utcnow() - datetime.timedelta(
                                 seconds=MATCH_HEARTBEAT_TIMEOUT_SECONDS)
                             )
        if args.get("ref"):
            query = query.filter(Server.ref == args.get("ref"))
        if args.get("version"):
            query = query.filter(Server.version == args.get("version"))
        if args.get("placement"):
            query = query.filter(Machine.placement == args.get("placement"))
        if args.get("realm"):
            query = query.filter(Machine.realm == args.get("realm"))
        if args.get("match_id"):
            query = query.filter(Match.match_id.in_(args.get("match_id")))
        player_ids = args["player_id"]

        query = query.order_by(-Match.num_players, -Match.server_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            include = True
            if player_ids:
                include = False

            match = row[0]
            server = row[1]
            machine = row[2]
            record = {}
            record["create_date"] = match.create_date
            record["game_mode"] = match.game_mode
            record["map_name"] = match.map_name
            record["max_players"] = match.max_players
            record["match_status"] = match.status
            record["server_status"] = server.status
            record["public_ip"] = server.public_ip
            record["port"] = server.port
            record["version"] = server.version
            record["match_id"] = match.match_id
            record["server_id"] = match.server_id
            record["machine_id"] = server.machine_id
            record["heartbeat_date"] = server.heartbeat_date
            record["realm"] = machine.realm
            record["placement"] = machine.placement
            record["ref"] = server.ref
            record["match_url"] = url_for("matches.entry",
                                          match_id=match.match_id,
                                          _external=True)
            record["server_url"] = url_for("servers.entry",
                                           server_id=server.server_id,
                                           _external=True)
            record["machine_url"] = url_for("machines.entry",
                                            machine_id=server.machine_id,
                                            _external=True)
            conn_url = "%s:%s?player_id=%s?token=%s"
            record["ue4_connection_url"] = conn_url % (server.public_ip,
                                                       server.port,
                                                       current_user["player_id"],
                                                       server.token)
            player_array = []
            players = g.db.query(MatchPlayer) \
                .filter(MatchPlayer.match_id == match.match_id,
                        MatchPlayer.status.in_(["active"])) \
                .all()
            for player in players:
                player_array.append({
                    "player_id": player.player_id,
                    "player_url": url_player(player.player_id),
                })
                if player.player_id in player_ids:
                    include = True
            record["players"] = player_array
            record["num_players"] = len(player_array)

            if include:
                ret.append(record)

        return jsonify(ret)


def unique_key_in_use(unique_key):
    if unique_key:
        query = g.db.query(Match, Server)
        existing_unique_match = query.filter(Match.server_id == Server.server_id,
                                             Match.status.notin_(["ended", "completed"]),
                                             Match.unique_key == unique_key,
                                             Server.status.in_(["started", "running", "active", "ready"]),
                                             Server.heartbeat_date >= utcnow() - datetime.timedelta(
                                                 seconds=MATCH_HEARTBEAT_TIMEOUT_SECONDS)
                                             ).first()
        return existing_unique_match is not None
    return False


def lock(redis):
    # Moving this into a separate function so systems test can mock it out.
    return redis.lock("ensure_match_unique_key")


class MatchPutRequestSchema(ma.Schema):
    status = ma.fields.String(required=True)

    server_id = ma.fields.Integer()
    num_players = ma.fields.Integer()
    max_players = ma.fields.Integer()
    map_name = ma.fields.String()
    game_mode = ma.fields.String()
    unique_key = ma.fields.String()
    match_statistics = ma.fields.Dict()
    details = ma.fields.Dict()


@bp.route('', endpoint='list')
class MatchesAPI(MethodView):
    """UE4 match
    """

    class MatchesAPIGetQuerySchema(ma.Schema):
        server_id = ma.fields.Integer()
        player_id = ma.fields.Integer()
        rows = ma.fields.Integer(load_default=DEFAULT_ROWS)
        use_pagination = ma.fields.Boolean(load_default=False)
        page = ma.fields.Integer(load_default=1)
        per_page = ma.fields.Integer(load_default=20)
        include_match_players = ma.fields.Boolean(load_default=False)
        game_mode = ma.fields.String()
        map_name = ma.fields.String()
        statistics_filter = ma.fields.String()
        details_filter = ma.fields.String()
        start_date = ma.fields.Date()

    @bp.arguments(MatchesAPIGetQuerySchema, location='query')
    def get(self, args):
        """This endpoint used by services and clients to fetch recent matches.
        Dump the DB rows out as json
        """

        log.info(f"Fetching matches for player {current_user.get('player_id', 'service')} with args {args}")

        is_service = current_user.get('is_service', False) or "service" in current_user["roles"]

        num_rows = args["rows"] or DEFAULT_ROWS
        server_id = args.get("server_id")

        # To prevent API breakage, use a separate implementation for pagination and make it opt-in.
        if args["use_pagination"]:
            player_id = args.get("player_id")
            game_mode = args.get("game_mode")
            map_name = args.get("map_name")
            statistics_filter = args.get("statistics_filter")
            details_filter = args.get("details_filter")
            start_date = args.get("start_date")

            if statistics_filter:
                try:
                    statistics_filter = json.loads(statistics_filter)
                except json.JSONDecodeError:
                    abort(http_client.BAD_REQUEST, description="Invalid statistics_filter")

            if details_filter:
                try:
                    details_filter = json.loads(details_filter)
                except json.JSONDecodeError:
                    abort(http_client.BAD_REQUEST, description="Invalid details_filter")

            if is_service:
                matches_query = g.db.query(Match)
            else:
                matches_query = g.db.query(
                    Match.match_id,
                    Match.start_date,
                    Match.end_date,
                    Match.max_players,
                    Match.game_mode,
                    Match.map_name,
                    Match.details,
                    Match.match_statistics,
                    Match.create_date,
                )

            if player_id:
                matches_query = matches_query.join(
                    MatchPlayer, and_(Match.match_id == MatchPlayer.match_id,
                                      MatchPlayer.player_id == player_id)
                )
                matches_query = matches_query.join(
                    MatchTeam, and_(MatchPlayer.team_id == MatchTeam.team_id,
                                    MatchTeam.match_id == Match.match_id)
                )
                is_winner = case(
                    [(cast(Match.match_statistics['winning_team_id'].astext, Integer) == MatchTeam.team_id, True)],
                    else_=False
                ).label("is_winner")
                matches_query = matches_query.add_columns(is_winner)

            if server_id:
                matches_query = matches_query.filter(Match.server_id == server_id)

            if game_mode:
                matches_query = matches_query.filter(Match.game_mode == game_mode)

            if map_name:
                matches_query = matches_query.filter(Match.map_name == map_name)

            if statistics_filter:
                for key, value in statistics_filter.items():
                    matches_query = matches_query.filter(Match.match_statistics[key].astext == value)

            if details_filter:
                for key, value in details_filter.items():
                    matches_query = matches_query.filter(Match.details[key].astext == value)

            if start_date:
                matches_query = matches_query.filter(func.date(Match.start_date) == start_date)

            matches_query = matches_query.order_by(-Match.match_id)

            matches_result = matches_query.paginate(page=args["page"], per_page=args["per_page"], error_out=True, max_per_page=num_rows)

            include_match_players = args["include_match_players"]

            matches = []
            for match_row in matches_result.items:
                if isinstance(match_row, Row):
                    if hasattr(match_row, 'Match'):
                        match_record = match_row.Match.as_dict()
                        if hasattr(match_row, 'is_winner'):
                            match_record["is_winner"] = match_row.is_winner
                    else:
                        match_record = match_row._asdict()
                elif isinstance(match_row, Match):
                    match_record = match_row.as_dict()
                else:
                    # pre SQLAlchemy 1.4 this would happen
                    match_record = match_row._asdict()

                match_id = match_record["match_id"]

                match_record["url"] = url_for("matches.entry", match_id=match_id, _external=True)
                match_record["matchplayers_url"] = url_for("matches.players", match_id=match_id, _external=True)
                match_record["teams_url"] = url_for("matches.teams", match_id=match_id, _external=True)

                if include_match_players:
                    # Fetch the match players
                    if is_service:
                        players_query = g.db.query(MatchPlayer, CorePlayer.player_name)
                    else:
                        players_query = g.db.query(
                            MatchPlayer.id,
                            MatchPlayer.match_id,
                            MatchPlayer.player_id,
                            MatchPlayer.team_id,
                            MatchPlayer.join_date,
                            MatchPlayer.leave_date,
                            MatchPlayer.statistics,
                            MatchPlayer.details,
                            MatchPlayer.create_date,
                            CorePlayer.player_name
                        )

                    players_query = players_query.join(CorePlayer, MatchPlayer.player_id == CorePlayer.player_id, isouter=True) \
                        .filter(MatchPlayer.match_id == match_id) \
                        .order_by(MatchPlayer.player_id)

                    players_result = players_query.all()

                    match_players = []
                    for player_row in players_result:
                        if is_service:
                            [match_player, player_name] = player_row
                            player_record = match_player.as_dict()
                            player_record["player_name"] = player_name or ""
                        else:
                            player_record = player_row._asdict()
                            player_record["player_name"] = player_record["player_name"] or ""

                        player_id = player_record["player_id"]
                        player_record["player_url"] = url_for("players.entry", player_id=player_id, _external=True)
                        player_record["matchplayer_url"] = url_for("matches.player", match_id=match_id, player_id=player_id, _external=True)
                        match_players.append(player_record)

                    match_record["players"] = match_players
                    match_record["num_players"] = len(match_players)

                    # Fetch the teams
                    if is_service:
                        teams_query = g.db.query(MatchTeam)
                    else:
                        teams_query = g.db.query(
                            MatchTeam.team_id,
                            MatchTeam.match_id,
                            MatchTeam.name,
                            MatchTeam.statistics,
                            MatchTeam.details,
                            MatchTeam.create_date,
                        )

                    teams_query = teams_query.filter(MatchTeam.match_id == match_id)

                    teams_result = teams_query.all()

                    match_teams = []
                    for team_row in teams_result:
                        if is_service:
                            team_record = team_row.as_dict()
                        else:
                            team_record = team_row._asdict()

                        team_record["url"] = url_for("matches.team", match_id=match_id, team_id=team_record["team_id"], _external=True)
                        match_teams.append(team_record)

                    match_record["teams"] = match_teams

                matches.append(match_record)

            ret = {
                "items": matches,
                "total": matches_result.total,
                "page": matches_result.page,
                "pages": matches_result.pages,
                "per_page": matches_result.per_page,
            }

            return jsonify(ret)

        query = g.db.query(Match)
        if server_id:
            query = query.filter(Match.server_id == server_id)
        query = query.order_by(-Match.match_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("matches.entry", match_id=row.match_id, _external=True)
            ret.append(record)
        return jsonify(ret)


    class MatchesPostRequestSchema(ma.Schema):
        server_id = ma.fields.Integer(required=True)

        num_players = ma.fields.Integer()
        max_players = ma.fields.Integer()
        map_name = ma.fields.String()
        game_mode = ma.fields.String()
        status = ma.fields.String()
        unique_key = ma.fields.String()
        match_statistics = ma.fields.Dict()
        details = ma.fields.Dict()
        num_teams = ma.fields.Integer(metadata=dict(
            description="Automatically create N teams with generic names. Mutually exclusive with team_names."))
        team_names = ma.fields.List(ma.fields.String(), metadata=dict(
            description="Create teams with specific names. Mutually exclusive with num_teams."))

    @requires_roles("service")
    @bp.arguments(MatchesPostRequestSchema)
    def post(self, args):
        """Register a new battle on the passed in match server.
        Each match server should always have a single battle.
        A match server will have zero matches only when it doesn't start up.
        Either the celery match server task (in normal EC2 mode) or the
        match server unreal process (in local development mode) will call
        this endpoint to create the battle resource.
        """
        server_id = args.get("server_id")
        unique_key = args.get("unique_key")
        details = args.get("details")

        num_teams = args.get("num_teams")
        team_names = args.get("team_names")

        if num_teams and team_names:
            abort(http_client.BAD_REQUEST, description="num_teams and team_names are mutually exclusive")

        log.info(f"Creating match for server {server_id} using {unique_key if unique_key else 'nothing'} as unique_key")

        with ExitStack() as stack:
            if unique_key:
                stack.enter_context(lock(g.redis))

            if unique_key_in_use(unique_key):
                log.info("Tried to set the unique key '{}' of a battle when one already exists".format(unique_key))
                abort(http_client.CONFLICT, description="An existing match with the same unique_key was found")

            match = Match(server_id=server_id,
                          num_players=args.get("num_players", 0),
                          max_players=args.get("max_players"),
                          map_name=args.get("map_name"),
                          game_mode=args.get("game_mode"),
                          status=args.get("status"),
                          status_date=utcnow(),
                          start_date=None,
                          match_statistics=args.get("match_statistics"),
                          details=details,
                          unique_key=unique_key,
                          )
            g.db.add(match)
            g.db.flush()
            # ! have to set this explicitly after the row is created
            match.start_date = None
            g.db.commit()
            match_id = match.match_id

            if num_teams:
                for i in range(num_teams):
                    team = MatchTeam(match_id=match_id,
                                     name="Team %s" % (i + 1)
                                     )
                    g.db.add(team)
                g.db.commit()

            if team_names:
                for team_name in team_names:
                    team = MatchTeam(match_id=match_id,
                                     name=team_name
                                     )
                    g.db.add(team)
                g.db.commit()

            resource_uri = url_for("matches.entry", match_id=match_id, _external=True)
            players_resource_uri = url_for("matches.players", match_id=match_id, _external=True)
            response_header = {
                "Location": resource_uri,
            }

            log.info("Created match %s for server %s", match_id, server_id)
            log_match_event(match_id, None, "gameserver.match.created",
                            details={"server_id": server_id})

            try:
                process_match_queue()
            except Exception:
                log.exception("Unable to process match queue")

            return jsonify({"match_id": match_id,
                            "url": resource_uri,
                            "players_url": players_resource_uri,
                            }), http_client.CREATED, response_header


@bp.route('/<int:match_id>', endpoint='entry')
class MatchAPI(MethodView):
    """
    Information about specific matches
    """

    @requires_roles("service")
    def get(self, match_id):
        """
        Find battle by ID

        Get information about a single battle. Dumps out the DB row as json
        URL's are provided for additional information about the battle for
        drilldown. Machine and matcheserver url's are also written out.
        """
        match = g.db.query(Match).get(match_id)
        if not match:
            abort(http_client.NOT_FOUND)

        ret = match.as_dict()
        ret["url"] = url_for("matches.entry", match_id=match_id, _external=True)

        server = g.db.query(Server).get(match.server_id)
        ret["server"] = None
        ret["server_url"] = None
        ret["machine_url"] = None
        if server:
            ret["server"] = server.as_dict()
            ret["server_url"] = url_for("servers.entry", server_id=server.server_id, _external=True)

            machine = g.db.query(Machine).get(server.machine_id)
            ret["machine"] = None
            if machine:
                ret["machine_url"] = url_for("machines.entry",
                                             machine_id=machine.machine_id, _external=True)

        teams = []
        rows = g.db.query(MatchTeam).filter(MatchTeam.match_id == match_id).all()
        for r in rows:
            team = r.as_dict()
            team["url"] = url_for("matches.team", match_id=match_id, team_id=r.team_id,
                                  _external=True)
            teams.append(team)
        ret["teams"] = teams

        ret["matchplayers_url"] = url_for("matches.players", match_id=match_id, _external=True)
        ret["teams_url"] = url_for("matches.teams", match_id=match_id, _external=True)

        players = []
        rows = g.db.query(MatchPlayer).filter(MatchPlayer.match_id == match_id).all()
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player", match_id=match_id,
                                                player_id=r.player_id, _external=True)
            player["player_url"] = url_player(r.player_id)
            players.append(player)
        ret["players"] = players
        ret["num_players"] = len(players)

        log.debug("Returning info for match %s", match_id)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchPutRequestSchema)
    def put(self, args, match_id):
        """
        Update battle status

        The UE4 server calls this method to update its status and any
        metadata that the backend should know about
        """

        log.debug("Updating battle %s", match_id)
        unique_key = args.get("unique_key")

        with ExitStack() as stack:
            if unique_key:
                stack.enter_context(lock(g.redis))

            match = g.db.query(Match).get(match_id)
            if not match:
                abort(http_client.NOT_FOUND)
            new_status = args.get("status")
            if match.status == "completed":
                log.warning("Trying to update a completed battle %d. Ignoring update", match_id)
                abort(http_client.BAD_REQUEST, description="Battle has already been completed.")

            current_unique_key = match.unique_key
            if unique_key and current_unique_key:
                log.info("Tried to update the unique key of a battle with a non-empty unique key '{}'->'{}'".format(
                    current_unique_key, unique_key))
                abort(http_client.CONFLICT, description="Battle unique key must not be changed from a non-empty value")

            if unique_key_in_use(unique_key):
                log.info("Tried to set the unique key '{}' of a battle when one already exists".format(unique_key))
                abort(http_client.CONFLICT, description="An existing match with the same unique_key was found")

            message_data = None
            if match.status != new_status:
                log.info("Changing status of match %s from '%s' to '%s'",
                         match_id, match.status, args["status"])

                message_data = {"event": "match_status_changed", "match_id": match_id, "match_status": new_status}

                if new_status == "started":
                    match.start_date = utcnow()
                elif new_status in ("completed", "ended"):
                    match.end_date = utcnow()
                    # ! TODO: Set leave_date on matchplayers who are still in the match
                match.status_date = utcnow()

            for arg in args:
                setattr(match, arg, args[arg])
            g.db.commit()

            if message_data:
                current_app.extensions["messagebus"].publish_message("match", message_data)

            resource_uri = url_for("matches.entry", match_id=match_id, _external=True)
            response_header = {
                "Location": resource_uri,
            }
            ret = {
                "match_id": match_id,
                "url": resource_uri,
            }

            log.info("Match %s has been updated.", match_id)

            return jsonify(ret), http_client.OK, response_header


class MatchTeamsPostRequestSchema(ma.Schema):
    name = ma.fields.String()
    statistics = ma.fields.Dict()
    details = ma.fields.Dict()


class MatchTeamPutRequestSchema(ma.Schema):
    name = ma.fields.String()
    statistics = ma.fields.Dict()
    details = ma.fields.Dict()


@bp.route('/<int:match_id>/teams', endpoint='teams')
class MatchTeamsAPI(MethodView):
    """
    All teams in a match
    """

    @requires_roles("service")
    def get(self, match_id):
        """
        Find teams by match
        """
        query = g.db.query(MatchTeam)
        query = query.filter(MatchTeam.match_id == match_id)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("matches.team",
                                    match_id=match_id,
                                    team_id=row.team_id,
                                    _external=True)
            ret.append(record)
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchTeamsPostRequestSchema)
    def post(self, args, match_id):
        """
        Add a team to a match
        """
        team = MatchTeam(match_id=match_id,
                         name=args.get("name"),
                         statistics=args.get("statistics"),
                         details=args.get("details"),
                         )
        g.db.add(team)
        g.db.commit()
        team_id = team.team_id
        resource_uri = url_for("matches.team", match_id=match_id, team_id=team_id, _external=True)
        response_header = {"Location": resource_uri}

        log.info("Created team %s for match %s", team_id, match_id)
        log_match_event(match_id,
                        None,
                        "gameserver.match.team_created",
                        details={"team_id": team_id})

        return jsonify({"team_id": team_id,
                        "url": resource_uri,
                        }), http_client.CREATED, response_header


@bp.route('/<int:match_id>/teams/<int:team_id>', endpoint='team')
class MatchTeamAPI(MethodView):
    """
    A specific team in a match
    """

    @requires_roles("service")
    def get(self, match_id, team_id):
        """
        Find a team in a match by ID's
        """
        query = g.db.query(MatchTeam)
        query = query.filter(MatchTeam.match_id == match_id,
                             MatchTeam.team_id == team_id)
        row = query.first()
        if not row:
            abort(http_client.NOT_FOUND)

        ret = row.as_dict()
        ret["url"] = url_for("matches.team", match_id=match_id, team_id=row.team_id, _external=True)

        query = g.db.query(MatchPlayer)
        query = query.filter(MatchPlayer.match_id == match_id,
                             MatchPlayer.team_id == team_id)
        rows = query.all()
        players = []
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player",
                                                match_id=match_id,
                                                player_id=r.player_id,
                                                _external=True)
            player["player_url"] = url_player(r.player_id)
            players.append(player)
        ret["players"] = players
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchTeamPutRequestSchema)
    def put(self, args, match_id, team_id):
        team = g.db.query(MatchTeam).get(team_id)
        if not team:
            abort(http_client.NOT_FOUND)
        for arg in args:
            setattr(team, arg, args[arg])
        g.db.commit()
        ret = team.as_dict()
        return jsonify(ret)


class MatchPlayerPostSchema(ma.Schema):
    player_id = ma.fields.Integer(required=True)
    team_id = ma.fields.Integer()


@bp.route('/<int:match_id>/players', endpoint='players')
class MatchPlayersAPI(MethodView):
    """
    Players in a specific match. The UE4 server will post to this endpoint
    to add a player to a match.
    """

    def get(self, match_id):
        """
        Get players from a match
        """
        rows = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id) \
            .all()
        ret = []
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player",
                                                match_id=match_id,
                                                player_id=r.player_id,
                                                _external=True)
            player["player_url"] = url_player(r.player_id)
            ret.append(player)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchPlayerPostSchema)
    def post(self, args, match_id):
        """
        Add a player to a match
        """
        log.info(f"POST to MatchPlayersAPI with match_id {match_id} and args {args}")
        player_id = args["player_id"]
        team_id = args.get("team_id", None)

        log.info(
            f"  dug up player_id {player_id} (type {type(player_id)}) and team_id {team_id} (type {type(team_id)})")
        match : Match | None = g.db.query(Match).get(match_id)
        if not match:
            log.warning(f" match {match_id} not found. Aborting")
            abort(http_client.NOT_FOUND, description="Match not found")

        if match.status == "completed":
            log.warning(f" match {match_id} is completed. Aborting")
            abort(http_client.BAD_REQUEST, description="You cannot add a player to a completed battle")

        num_players = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match.match_id,
                    MatchPlayer.status.in_(["active"])) \
            .count()
        if num_players >= match.max_players:
            log.warning(f" match {match_id} has {num_players} and maximum is {match.max_players}. Aborting")
            abort(http_client.BAD_REQUEST, description="Match is full")

        if team_id:
            team = g.db.query(MatchTeam).get(team_id)
            if not team:
                log.warning(f" team_id {team_id} not found. Aborting.")
                abort(http_client.NOT_FOUND, description="Team not found")
            if team.match_id != match_id:
                log.warning(
                    f" team_id {team_id} doesn't belong to match {match_id}, it belongs to match {team.match_id}. Aborting.")
                abort(http_client.BAD_REQUEST,
                      description="Team %s is not in match %s" % (team_id, match_id))

        match_player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id,
                    MatchPlayer.player_id == player_id) \
            .first()
        if not match_player:
            log.info(f" player {player_id} not found in match already. Adding him...")
            match_player = MatchPlayer(match_id=match_id,
                                       player_id=player_id,
                                       team_id=team_id,
                                       num_joins=0,
                                       seconds=0,
                                       status="active")
            g.db.add(match_player)
        
        try:
            RichPresenceService(g.db, g.redis, current_user).set_match_status(player_id, match.map_name, match.game_mode)
        except Exception as e:
            log.exception(f"Failed to set match status while adding player to match. {e}")

        match_player.num_joins += 1
        match_player.join_date = utcnow()
        match_player.status = "active"

        # remove the player from the match queue
        g.db.query(MatchQueuePlayer).filter(MatchQueuePlayer.player_id == player_id).delete()

        if match.start_date is None:
            match.start_date = utcnow()

        g.db.commit()

        # prepare the response
        resource_uri = url_for("matches.player",
                               match_id=match_id,
                               player_id=player_id,
                               _external=True)
        response_header = {"Location": resource_uri}
        log.info("Player %s has joined match %s in team %s.", player_id, match_id, team_id)

        log_match_event(match_id, player_id, "gameserver.match.player_joined",
                        details={"team_id": team_id})

        return jsonify({"match_id": match_id,
                        "player_id": player_id,
                        "team_id": team_id,
                        "url": resource_uri,
                        }), http_client.CREATED, response_header


@bp.route('/<int:match_id>/players/<int:player_id>', endpoint='player')
class MatchPlayerAPI(MethodView):
    """
    A specific player in a specific match
    """

    class MatchPlayerPatchRequestSchema(ma.Schema):
        status = ma.fields.String()
        team_id = ma.fields.Integer()
        statistics = ma.fields.Dict()
        details = ma.fields.Dict()

    def get(self, match_id, player_id):
        """
        Get a specific player from a battle
        """
        player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id, MatchPlayer.player_id == player_id) \
            .first()
        if not player:
            abort(http_client.NOT_FOUND)

        ret = player.as_dict()
        ret["team_url"] = None
        if player.team_id:
            ret["team_url"] = url_for("matches.team", match_id=match_id,
                                      team_id=player.team_id, _external=True)
        ret["player_url"] = url_player(player_id)
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchPlayerPatchRequestSchema)
    def patch(self, args, match_id, player_id):
        """
        Update a specific player in a battle
        """
        match_player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id,
                    MatchPlayer.player_id == player_id) \
            .first()

        if not match_player:
            log.info(f"player {player_id} not found in match {match_id}. Aborting.")
            abort(http_client.NOT_FOUND)

        if args.get("status") == "banned" and match_player.status != "banned":
            match_type = args.get("details", {}).get("match_type")
            log.info(f"Player {player_id} is banned from battle {match_id} ({match_type})")
            log_match_event(match_id, player_id,"gameserver.match.player_banned")
            current_app.extensions["messagebus"].publish_message("match", {
                "event": "match_player_banned", "match_id": match_id, "match_type": match_type, "player_id": player_id})

        for attr, value in args.items():
            setattr(match_player, attr, value)
        g.db.commit()

        log.info("Player %s updated in match %s", player_id, match_id)
        log_match_event(match_id, player_id, "gameserver.match.player_updated", details=args)

        ret = match_player.as_dict()
        ret["player_url"] = url_player(player_id)
        ret["team_url"] = None

        if match_player.team_id:
            ret["team_url"] = url_for("matches.team", match_id=match_id, team_id=match_player.team_id, _external=True)

        return jsonify(ret)

    @requires_roles("service")
    def delete(self, match_id, player_id):
        """
        A player has left an ongoing battle
        """
        match_player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id,
                    MatchPlayer.player_id == player_id) \
            .first()
        if not match_player:
            log.info(f"player {player_id} not found in match {match_id}. Aborting.")
            abort(http_client.NOT_FOUND)

        if match_player.status != "active":
            log.info(f"player {player_id} in match {match_id} isn't active. Aborting.")
            abort(http_client.BAD_REQUEST, description="Player status must be active, not '%s'" %
                                                       match_player.status)

        match = g.db.query(Match).get(match_id)
        if not match:
            log.info(f"match {match_id} not found. Aborting.")
            abort(http_client.NOT_FOUND, description="Match not found")

        if match.status == "completed":
            log.warning("Attempting to remove player %s from battle %s which has already completed",
                        player_id, match_id)
            abort(http_client.BAD_REQUEST,
                  description="You cannot remove a player from a completed match")

        team_id = match_player.team_id

        match_player.status = "quit"

        try:
            RichPresenceService(g.db, g.redis, current_user).clear_match_status(player_id)
        except Exception as e:
            log.exception(f"Failed to set clear match status during player-left-match. {e}")


        num_seconds = (utcnow() - match_player.join_date).total_seconds()
        match_player.leave_date = utcnow()
        match_player.seconds += num_seconds

        g.db.commit()

        log.info("Player %s has left battle %s", player_id, match_id)
        log_match_event(match_id, player_id,
                        "gameserver.match.player_left",
                        details={"team_id": team_id})
        message_data = {"event": "match_player_left", "match_id": match_id, "player_id": player_id}
        current_app.extensions["messagebus"].publish_message("match", message_data)
        return jsonify({"message": "Player has left the battle"})


@endpoints.register
def endpoint_info(*args):
    ret = {
        "active_matches": url_for("matches.active", _external=True),
        "matches": url_for("matches.list", _external=True),
    }
    return ret
