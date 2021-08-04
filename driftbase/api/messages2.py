"""
    Message box, mostly meant for client-to-client communication
"""
import copy

import collections
import datetime
import gevent
import http.client
import http.client as http_client
import json
import logging
import marshmallow as ma
import operator
from flask import g, url_for, stream_with_context, Response, jsonify
from flask.views import MethodView
from flask_restx import reqparse
from flask_smorest import Blueprint, abort

from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

log = logging.getLogger(__name__)

bp = Blueprint("messages2", __name__, url_prefix="/messages2",
               description="Service to player, and player to player message bus")

endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


# messages expire in a day by default
DEFAULT_EXPIRE_SECONDS = 60 * 60 * 24
# prune a player's message list if they're not listening
MAX_PENDING_MESSAGES = 100

# for mocking
def utcnow():
    return datetime.datetime.utcnow()


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime.datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


def is_key_legal(key):
    if len(key) > 64:
        return False
    if ":" in key:
        return False
    return True


def _next_message_id(message_id):
    """ Return the minimum valid increment to the passed in message_id """
    id_parts = message_id.split('-')
    if len(id_parts) == 2:
        id_parts[1] = f"{int(id_parts[1]) + 1}"
    else:
        id_parts.append('1')
    return '-'.join(id_parts)


def fetch_messages(exchange, exchange_id, messages_after_id=None, rows=None):
    messages = []
    redis_messages_key = g.redis.make_key("messages2:%s-%s" % (exchange, exchange_id))
    redis_seen_key = g.redis.make_key("messages2:seen:%s-%s" % (exchange, exchange_id))
    my_player_id = None
    if current_user:
        my_player_id = current_user["player_id"]

    seen_message_id = g.redis.conn.get(redis_seen_key)
    if messages_after_id == '0' and seen_message_id:
        messages_after_id = seen_message_id
    else:
        g.redis.conn.set(redis_seen_key, messages_after_id)

    highest_processed_message_id = '0'

    from_message_id = _next_message_id(messages_after_id)
    content = g.redis.conn.xrange(redis_messages_key, min=from_message_id, max='+', count=rows)

    now = utcnow()
    expired_ids = []
    if len(content):
        for message_id, message in content:
            message['payload'] = json.loads(message['payload'])
            message['message_id'] = message_id
            highest_processed_message_id = message_id
            expires = datetime.datetime.fromisoformat(message["expires"][:-1])  # remove trailing 'Z'
            if expires > now:
                messages.append(message)
                log.debug("Message %s has been retrieved from queue '%s' in "
                          "exchange '%s-%s' by player %s",
                          message['message_id'],
                          message['queue'], exchange, exchange_id, my_player_id)
            else:
                expired_ids += message_id
                log.debug("Expired message %s was removed from queue '%s' in "
                          "exchange '%s-%s' by player %s",
                          message['message_id'],
                          message['queue'], exchange, exchange_id, my_player_id)

    with g.redis.conn.pipeline() as pipe:
        # If there were only expired messages, make sure we skip those next time
        if len(messages) == 0 and highest_processed_message_id != '0':
            pipe.set(redis_seen_key, highest_processed_message_id)

        # Delete expired messages
        if expired_ids:
            pipe.xdel(redis_messages_key, expired_ids)
        pipe.execute()

    result = collections.defaultdict(list)
    for m in messages:
        result[m['queue']].append(m)
    return result


def is_service():
    ret = False
    if current_user and 'service' in current_user['roles']:
        ret = True
    return ret


def check_can_use_exchange(exchange, exchange_id, read=False):
    # service users have unrestricted access to all exchanges
    if is_service():
        return True

    # players can only use player exchanges
    if exchange != "players":
        abort(http_client.BAD_REQUEST, message="Only service users can use exchange '%s'" % exchange)

    # players can only read from their own exchanges but can write to others
    if read:
        if not current_user or current_user["player_id"] != exchange_id:
            abort(http_client.BAD_REQUEST,
                  message="You can only read from an exchange that belongs to you!")


class MessageExchangeAPI2GetResponseItem(ma.Schema):
    exchange = ma.fields.String()
    exchange_id = ma.fields.Integer()
    queue = ma.fields.String()
    payload = ma.fields.Dict()
    expire_seconds = ma.fields.String()
    message_id = ma.fields.String()


class MessageExchangeAPI2GetResponse(ma.Schema):
    data = ma.fields.Dict(keys=ma.fields.Str(), values=ma.fields.List(ma.fields.Nested(MessageExchangeAPI2GetResponseItem)))


@bp.route('/<string:exchange>/<int:exchange_id>', endpoint='exchange')
class MessagesExchangeAPI2(MethodView):
    no_jwt_check = ["GET"]

    get_args = reqparse.RequestParser()
    get_args.add_argument("timeout", type=int)
    get_args.add_argument("messages_after", type=str)
    get_args.add_argument("rows", type=int)

    @bp.response(http.client.OK, MessageExchangeAPI2GetResponse)
    def get(self, exchange, exchange_id):
        check_can_use_exchange(exchange, exchange_id, read=True)

        args = self.get_args.parse_args()
        timeout = args.timeout or 0
        messages_after = args.messages_after or '0'
        rows = args.rows
        if rows:
            rows = int(rows)

        my_player_id = None
        if current_user:
            my_player_id = current_user["player_id"]

        # players can only use player exchanges
        if exchange != "players" and not is_service():
            abort(http_client.BAD_REQUEST,
                  message="Only service users can use exchange '%s'" % exchange)

        exchange_full_name = "{}-{}".format(exchange, exchange_id)
        start_time = utcnow()
        poll_timeout = utcnow()

        res = dict(data={})
        if timeout > 0:
            poll_timeout += datetime.timedelta(seconds=timeout)
            log.debug("[%s] Long poll - Waiting %s seconds for messages...", my_player_id, timeout)

            def streamer():
                yield " "
                while 1:
                    try:
                        messages = fetch_messages(exchange, exchange_id, messages_after, rows)
                        if messages:
                            log.debug("[%s/%s] Returning messages after %.1f seconds",
                                      my_player_id, exchange_full_name,
                                      (utcnow() - start_time).total_seconds())
                            yield json.dumps(messages, default=json_serial)
                            return
                        elif utcnow() > poll_timeout:
                            log.debug("[%s/%s] Poll timeout with no messages after %.1f seconds",
                                      my_player_id, exchange_full_name,
                                      (utcnow() - start_time).total_seconds())
                            yield res
                            return
                        # sleep for 100ms
                        gevent.sleep(0.1)
                        yield " "
                    except Exception as e:
                        log.error("[%s/%s] Exception %s", my_player_id, exchange_full_name, repr(e))
                        yield res

            return Response(stream_with_context(streamer()), mimetype="application/json")
        else:
            messages = fetch_messages(exchange, exchange_id, messages_after, rows)
            res['data'] = messages
            return res


class MessagesQueue2PostArgs(ma.Schema):
    message = ma.fields.Dict(required=True)
    expire = ma.fields.Integer()


class MessagesQueue2PostResponse(ma.Schema):
    exchange = ma.fields.String()
    exchange_id = ma.fields.Integer()
    queue = ma.fields.String()
    payload = ma.fields.Dict()
    expire_seconds = ma.fields.String()
    message_id = ma.fields.String()
    url = ma.fields.Url()


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>', endpoint='queue')
class MessagesQueueAPI2(MethodView):

    @bp.arguments(MessagesQueue2PostArgs)
    @bp.response(http.client.CREATED, MessagesQueue2PostResponse)
    def post(self, args, exchange, exchange_id, queue):
        check_can_use_exchange(exchange, exchange_id, read=False)
        expire_seconds = args.get('expire') or DEFAULT_EXPIRE_SECONDS

        message_info = post_message(
            exchange=exchange,
            exchange_id=exchange_id,
            queue=queue,
            payload=args['message'],
            expire_seconds=expire_seconds,
        )

        log.debug(
            "Message %s has been added to queue '%s' in exchange "
            "'%s-%s' by player %s. It will expire on '%s'",
            message_info['message_id'],
            queue, exchange, exchange_id,
            current_user['player_id'] if current_user else None,
            expire_seconds
        )

        resource_url = url_for(
            'messages2.message',
            exchange=exchange,
            exchange_id=exchange_id,
            queue=queue,
            message_id=message_info['message_id'],
            _external=True
        )

        ret = copy.copy(message_info)
        ret['url'] = resource_url

        response_headers = {
            'Location': resource_url
        }
        return ret, http.client.CREATED, response_headers


def post_message(exchange, exchange_id, queue, payload, expire_seconds=None, sender_system=False):
    if not is_key_legal(exchange) or not is_key_legal(queue):
        abort(http_client.BAD_REQUEST, message="Exchange or Queue name is invalid.")

    expire_seconds = expire_seconds or DEFAULT_EXPIRE_SECONDS
    timestamp = utcnow()
    expires = timestamp + datetime.timedelta(seconds=expire_seconds)
    message = {
        'timestamp': timestamp.isoformat() + "Z",
        'expires': expires.isoformat() + "Z",
        'sender_id': 0 if sender_system else current_user["player_id"],
        'payload': json.dumps(payload, default=json_serial),
        'queue': queue,
        'exchange': exchange,
        'exchange_id': exchange_id,
    }

    message_id = g.redis.conn.xadd(g.redis.make_key("messages2:%s-%s" % (exchange, exchange_id)), message, id='*', maxlen=MAX_PENDING_MESSAGES)

    return {
        'message_id': message_id
    }


class MessageQueueAPI2Response(ma.Schema):
    exchange = ma.fields.String()
    exchange_id = ma.fields.Integer()
    queue = ma.fields.String()
    payload = ma.fields.Dict()
    expire_seconds = ma.fields.String()
    message_id = ma.fields.String()


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>/<string:message_id>', endpoint='message')
class MessageQueueAPI2(MethodView):

    @bp.response(http.client.OK, MessageQueueAPI2Response)
    def get(self, exchange, exchange_id, queue, message_id):
        check_can_use_exchange(exchange, exchange_id, read=True)

        key = g.redis.make_key("messages2:%s-%s" % (exchange, exchange_id))
        val = g.redis.conn.xrange(key, min=message_id, max=message_id, count=1)
        if val:
            message = val[0][1]
            message['payload'] = json.loads(message['payload'])
            return message
        else:
            abort(http_client.NOT_FOUND)


@endpoints.register
def endpoint_info(*args):
    return {
        "my_messages2": url_for("messages2.exchange", exchange="players", exchange_id=current_user["player_id"],
                                _external=True) if current_user else None
    }
