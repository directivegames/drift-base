import datetime
import logging
import uuid

import marshmallow as ma
from flask import url_for, g, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint, abort
import http.client as http_client

from drift.core.extensions.jwt import current_user, requires_roles
from drift.core.extensions.urlregistry import Endpoints
from driftbase.config import get_server_heartbeat_config
from driftbase.models.db import (
    Machine, Server, Match, ServerDaemonCommand
)

log = logging.getLogger(__name__)

bp = Blueprint("servers", __name__, url_prefix="/servers")
endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


def utcnow():
    return datetime.datetime.utcnow()


class ServersGetArgsSchema(ma.Schema):
    machine_id = ma.fields.Integer()
    rows = ma.fields.Integer()


class ServersPostRequestSchema(ma.Schema):
    machine_id = ma.fields.Integer()
    version = ma.fields.String()
    public_ip = ma.fields.IPv4()
    port = ma.fields.Integer()
    command_line = ma.fields.String()
    command_line_custom = ma.fields.String()
    pid = ma.fields.Integer()
    status = ma.fields.String()
    image_name = ma.fields.String()
    instance_name = ma.fields.String()
    branch = ma.fields.String()
    commit_id = ma.fields.String()
    process_info = ma.fields.Dict()
    details = ma.fields.Dict()
    repository = ma.fields.String()
    ref = ma.fields.String()
    build = ma.fields.String()
    build_number = ma.fields.Integer()
    target_platform = ma.fields.String()
    build_info = ma.fields.Dict()
    placement = ma.fields.String()


class ServersPostResponseSchema(ma.Schema):
    server_id = ma.fields.Integer(required=True)
    machine_id = ma.fields.Integer(required=True)
    url = ma.fields.Url(required=True)
    machine_url = ma.fields.Url(required=True)
    heartbeat_url = ma.fields.Url(required=True)
    commands_url = ma.fields.Url(required=True)
    token = ma.fields.String(required=True)
    next_heartbeat_seconds = ma.fields.Number(required=True)
    heartbeat_timeout = ma.fields.Str(required=True)


class ServerPutRequestSchema(ma.Schema):
    status = ma.fields.String(required=True)

    machine_id = ma.fields.Integer()
    version = ma.fields.String()
    public_ip = ma.fields.IPv4()
    port = ma.fields.Integer()
    command_line = ma.fields.String()
    command_line_custom = ma.fields.String()
    pid = ma.fields.Integer()
    image_name = ma.fields.String()
    error = ma.fields.String()
    branch = ma.fields.String()
    commit_id = ma.fields.String()
    process_info = ma.fields.Dict()
    details = ma.fields.Dict()
    repository = ma.fields.String()
    ref = ma.fields.String()
    build = ma.fields.String()
    build_number = ma.fields.Integer()
    target_platform = ma.fields.String()
    build_info = ma.fields.Dict()


class ServerPutResponseSchema(ma.Schema):
    server_id = ma.fields.Integer(required=True)
    machine_id = ma.fields.Integer(required=True)
    url = ma.fields.Url(required=True)
    machine_url = ma.fields.Url(required=True)
    heartbeat_url = ma.fields.Url(required=True)


class ServerHeartbeatPutResponseSchema(ma.Schema):
    last_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of the previous heartbeat"))
    this_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of this heartbeat"))
    next_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp when the next heartbeat is expected"))
    next_heartbeat_seconds = ma.fields.Integer(metadata=dict(description="Number of seconds until the next heartbeat is expected"))
    heartbeat_timeout = ma.fields.DateTime(
        metadata=dict(description="Timestamp when the server times out if no heartbeat is received"))
    heartbeat_timeout_seconds = ma.fields.Integer(
        metadata=dict(description="Number of seconds until the server times out if no heartbeat is received"))


@bp.route('', endpoint='list')
class ServersAPI(MethodView):
    @requires_roles("service")
    @bp.arguments(ServersGetArgsSchema, location='query')
    def get(self, args):
        """
        Get a list of the last 100 battle servers that have been registered in
        the system.
        """
        num_rows = args.get("rows") or 100
        query = g.db.query(Server)
        if args.get("machine_id"):
            query = query.filter(Server.machine_id == args.get("machine_id"))
        query = query.order_by(-Server.server_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("servers.entry", server_id=row.server_id, _external=True)
            ret.append(record)
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(ServersPostRequestSchema)
    @bp.response(http_client.CREATED, ServersPostResponseSchema)
    def post(self, args):
        """
        The daemon process (and server, for local development) post here
        to register the server instance with the backend. You need to
        register the server before you can register a battle.
        """
        machine_id = args.get("machine_id")
        log.info("registering a server on machine_id %s, realm %s and public_ip %s",
                 machine_id, args.get("realm"), args.get("public_ip"))
        # If we don't already have a machine we make one just in time now on the realm "Local".
        # This is to support local devs where an external daemon is not running and the server iself
        # does this registration without a prior registration on the machines endpoint
        if not machine_id:
            realm = "local"
            instance_name = args.get("instance_name")
            placement = args.get("placement") or "<unknown placement>"
            if not instance_name:
                abort(http_client.BAD_REQUEST, description="You need to supply an instance_name")

            machine = g.db.query(Machine).filter(Machine.realm == realm,
                                                 Machine.instance_name == instance_name,
                                                 Machine.placement == placement).first()
            if machine:
                machine_id = machine.machine_id
                log.info("machine_id %s found for server", machine_id)
            else:
                machine = Machine(realm=realm, instance_name=instance_name,
                                  placement=placement, server_count=0)
                g.db.add(machine)
                g.db.flush()
                machine_id = machine.machine_id
                log.info("Created machine_id %s for server instance \"%s\"",
                         machine_id, instance_name)
        else:
            machine = g.db.query(Machine).get(machine_id)
            if not machine:
                abort(http_client.NOT_FOUND, description="Machine %s was not found" % machine_id)

        token = str(uuid.uuid4()).replace("-", "")[:20]

        def get_or_null(ip):
            return ip and str(ip) or None

        server = Server(machine_id=machine_id,
                        version=args.get("version"),
                        public_ip=get_or_null(args.get("public_ip")),
                        port=args.get("port"),
                        command_line=args.get("command_line"),
                        command_line_custom=args.get("command_line_custom"),
                        pid=args.get("pid"),
                        status=args.get("status"),
                        image_name=args.get("image_name"),
                        branch=args.get("branch"),
                        commit_id=args.get("commit_id"),
                        process_info=args.get("process_info"),
                        details=args.get("details"),
                        repository=args.get("repository"),
                        ref=args.get("ref"),
                        build=args.get("build"),
                        build_number=args.get("build_number"),
                        target_platform=args.get("target_platform"),
                        build_info=args.get("build_info"),
                        token=token
                        )
        g.db.add(server)

        machine.server_count += 1
        machine.server_date = utcnow()
        g.db.commit()

        server_id = server.server_id

        resource_url = url_for("servers.entry", server_id=server_id, _external=True)
        machine_url = url_for("machines.entry", machine_id=machine_id, _external=True)
        heartbeat_url = url_for("servers.heartbeat", server_id=server_id, _external=True)
        commands_url = url_for("servers.commands", server_id=server_id, _external=True)
        response_header = {
            "Location": resource_url,
        }
        log.info("Server %s has been registered on machine_id %s", server_id, machine_id)
        heartbeat_period, heartbeat_timeout = get_server_heartbeat_config()
        return {"server_id": server_id,
                "url": resource_url,
                "machine_id": machine_id,
                "machine_url": machine_url,
                "heartbeat_url": heartbeat_url,
                "commands_url": commands_url,
                "token": token,
                "next_heartbeat_seconds": heartbeat_period,
                "heartbeat_timeout": utcnow() + datetime.timedelta(seconds=heartbeat_timeout),
                }, None, response_header


@bp.route('/<int:server_id>', endpoint='entry')
class ServerAPI(MethodView):
    """
    Interface to battle servers instances. A battle server instance is
    a single run of a battle server executable. The battle server will
    have a single battle on it. You should never have a battle resource
    without an associated battle server resource.
    """

    @requires_roles("service")
    def get(self, server_id):
        """
        Get information about a single battle server instance.
        Returns information from the machine and the associated
        battle if found.
        """
        server = g.db.query(Server).get(server_id)

        if not server:
            log.warning("Requested a non-existant battle server: %s", server_id)
            abort(http_client.NOT_FOUND, description="Server not found")

        machine_id = server.machine_id
        record = server.as_dict()
        record["url"] = url_for("servers.entry", server_id=server_id, _external=True)
        record["heartbeat_url"] = url_for("servers.heartbeat", server_id=server_id, _external=True)
        record["commands_url"] = url_for("servers.commands", server_id=server_id, _external=True)

        record["machine_url"] = None
        if machine_id:
            machine = g.db.query(Machine).get(machine_id)
            if machine:
                record["machine_url"] = url_for("machines.entry", machine_id=machine_id,
                                                _external=True)

        matches = []
        rows = g.db.query(Match).filter(Match.server_id == server_id).all()
        for row in rows:
            match_id = row.match_id
            match = {"match_id": match_id,
                     "url": url_for("matches.entry", match_id=match_id, _external=True),
                     "num_players": row.num_players,
                     }
            matches.append(match)
        record["matches"] = matches

        commands = []
        rows = g.db.query(ServerDaemonCommand).filter(ServerDaemonCommand.server_id == server_id,
                                                      ServerDaemonCommand.status == "pending").all()
        for row in rows:
            command = {"command_id": row.command_id,
                       "command": row.command,
                       "arguments": row.arguments,
                       "create_date": row.create_date,
                       "url": url_for("servers.command", server_id=server_id,
                                      command_id=row.command_id, _external=True)
                       }
            commands.append(command)
        record["pending_commands"] = commands

        log.debug("Returning info for battle server %s", server_id)
        return jsonify(record)

    @requires_roles("service")
    @bp.arguments(ServerPutRequestSchema)
    @bp.response(http_client.OK, ServerPutResponseSchema)
    def put(self, args, server_id):
        """
        The battle server management (celery) process calls this to update
        the status of running a specific battle server task
        """
        log.info("Updating battle server %s", server_id)
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(http_client.NOT_FOUND)
        if args.get("status"):
            log.info("Changing status of battle server %s from '%s' to '%s'",
                     server_id, server.status, args["status"])
        public_ip = args.pop("public_ip", None)
        if public_ip:
            server.public_ip = str(public_ip)
        for arg in args:
            setattr(server, arg, args[arg])
        g.db.commit()

        machine_id = server.machine_id
        machine_url = None
        if machine_id:
            machine_url = url_for("machines.entry", machine_id=machine_id, _external=True)

        return {"server_id": server_id,
                "url": url_for("servers.entry", server_id=server_id, _external=True),
                "machine_id": machine_id,
                "machine_url": machine_url,
                "heartbeat_url": url_for("servers.heartbeat", server_id=server_id, _external=True),
                }


@bp.route('/<int:server_id>/heartbeat', endpoint='heartbeat')
class ServerHeartbeatAPI(MethodView):
    """
    Thin heartbeat API
    """

    @requires_roles("service")
    @bp.response(http_client.OK, ServerHeartbeatPutResponseSchema)
    def put(self, server_id):
        """
        Battle server heartbeat
        """
        log.debug("%s is heart beating battle server %s",
                  current_user.get("user_name", "unknown"), server_id)
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(http_client.NOT_FOUND, description="Server not found")

        heartbeat_period, heartbeat_timeout = get_server_heartbeat_config()

        now = utcnow()
        last_heartbeat = server.heartbeat_date
        if last_heartbeat + datetime.timedelta(seconds=heartbeat_timeout) < now:
            msg = "Heartbeat timeout. Last heartbeat was at {} and now we are at {}" \
                .format(last_heartbeat, now)
            log.info(msg)
            abort(http_client.NOT_FOUND, message=msg)
        server.heartbeat_count += 1
        server.heartbeat_date = now
        g.db.commit()

        return {
            "last_heartbeat": last_heartbeat,
            "this_heartbeat": server.heartbeat_date,
            "next_heartbeat": server.heartbeat_date + datetime.timedelta(seconds=heartbeat_period),
            "next_heartbeat_seconds": heartbeat_period,
            "heartbeat_timeout": now + datetime.timedelta(seconds=heartbeat_timeout),
            "heartbeat_timeout_seconds": heartbeat_timeout,
        }


class ServerCommandsPostSchema(ma.Schema):
    command = ma.fields.String(required=True)
    arguments = ma.fields.Dict()
    details = ma.fields.Dict()


@bp.route('/<int:server_id>/commands', endpoint='commands')
class ServerCommandsAPI(MethodView):
    """
    Commands for the battle server daemon
    """

    @requires_roles("service")
    @bp.arguments(ServerCommandsPostSchema)
    def post(self, args, server_id):
        """
        Add a new command for the daemon to execute
        """
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(http_client.NOT_FOUND)

        status = "pending"
        command = ServerDaemonCommand(server_id=server_id,
                                      command=args["command"],
                                      arguments=args.get("arguments"),
                                      details=args.get("details"),
                                      status=status,
                                      )
        g.db.add(command)
        g.db.commit()

        resource_url = url_for("servers.command", server_id=server_id,
                               command_id=command.command_id, _external=True)
        return jsonify({"command_id": command.command_id,
                        "url": resource_url,
                        "status": status,
                        }), http_client.CREATED, None

    @requires_roles("service")
    def get(self, server_id):
        rows = g.db.query(ServerDaemonCommand) \
            .filter(ServerDaemonCommand.server_id == server_id) \
            .all()
        ret = []
        for r in rows:
            command = r.as_dict()
            command["url"] = url_for("servers.command",
                                     server_id=server_id,
                                     command_id=r.command_id,
                                     _external=True)
            ret.append(command)
        return jsonify(ret)


class ServerCommandPatchSchema(ma.Schema):
    status = ma.fields.String(required=True)
    details = ma.fields.Dict()


@bp.route('/<int:server_id>/commands/<int:command_id>', endpoint='command')
class ServerCommandAPI(MethodView):
    @requires_roles("service")
    @bp.arguments(ServerCommandPatchSchema)
    def patch(self, args, server_id, command_id):
        return self._patch(args, server_id, command_id)

    @requires_roles("service")
    @bp.arguments(ServerCommandPatchSchema)
    def put(self, args, server_id, command_id):
        return self._patch(args, server_id, command_id)

    def _patch(self, args, server_id, command_id):
        """
        Add a new command for the daemon to execute
        """
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(http_client.NOT_FOUND)

        row = g.db.query(ServerDaemonCommand).get(command_id)
        row.status = args["status"]
        row.status_date = utcnow()
        if "details" in args:
            row.details = args["details"]
        g.db.commit()

        ret = row.as_dict()
        ret["url"] = url_for("servers.command", server_id=server_id, command_id=row.command_id,
                             _external=True)
        return jsonify(ret)

    @requires_roles("service")
    def get(self, server_id, command_id):
        row = g.db.query(ServerDaemonCommand).get(command_id)
        ret = row.as_dict()
        ret["url"] = url_for("servers.command", server_id=server_id, command_id=row.command_id,
                             _external=True)
        return jsonify(ret)


@endpoints.register
def endpoint_info(*args):
    ret = {"servers": url_for("servers.list", _external=True), }
    return ret
