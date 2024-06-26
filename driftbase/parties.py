import logging
from time import time

from flask import g, url_for, current_app
from redis import WatchError
import http.client as http_client
from webargs.flaskparser import abort
from driftbase.messages import post_message

from driftbase.resources.parties import TIER_DEFAULTS

log = logging.getLogger(__name__)


OPERATION_TIMEOUT = 10


# Redis keys used:
# party_invite:id: NEXT_PARTY_INVITE_ID - The next available party invite ID
# party:id: NEXT_PARTY_ID - The next available party ID
# party_invite:INVITE_ID: (from:PLAYER_ID to:PLAYER_ID) - HSET from which player to which player
# party_players:PARTY_ID: [PLAYER_ID, ...] - SET of players
# player:PLAYER_ID:invites: [INVITE_ID, ...] - ZSET of invite ID by invited player ID
# player:PLAYER_ID:party: PARTY_ID - Current player party ID


def get_max_players_per_party():
    tenant = g.conf.tenant
    max_players = TIER_DEFAULTS['max_players_per_party']
    if tenant and 'parties' in tenant:
        parties_config = tenant['parties']
        max_players = parties_config.get('max_players_per_party', max_players)
    return max_players



def accept_party_invite(invite_id, sending_player, accepting_player, leave_existing_party = False):
    max_players_per_party = get_max_players_per_party()
    sending_player_party_key = make_player_party_key(sending_player)
    accepting_player_party_key = make_player_party_key(accepting_player)
    sending_player_invites_key = make_player_invites_key(sending_player)
    invite_key = make_party_invite_key(invite_id)
    party_id_key = g.redis.make_key("party:id:")
    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(invite_key, accepting_player_party_key, sending_player_party_key, sending_player_invites_key)

                # Get player and invite details
                pipe.multi()
                pipe.get(sending_player_party_key)
                pipe.get(accepting_player_party_key)
                pipe.hgetall(invite_key)
                sending_player_party_id, accepting_player_party_id, invite = pipe.execute()

                # Check that everything is valid
                if not invite:
                    abort(http_client.NOT_FOUND)

                if int(invite['from']) != sending_player or int(invite['to']) != accepting_player:
                    abort(http_client.BAD_REQUEST, message="Invite doesn't match players")

                # Check existing party
                if accepting_player_party_id and sending_player_party_id != accepting_player_party_id:
                    if not leave_existing_party:
                        abort(http_client.BAD_REQUEST, message="You must leave your current party first")

                    leave_party(accepting_player, int(accepting_player_party_id))

                if sending_player_party_id and len(get_party_members(int(sending_player_party_id))) >= max_players_per_party:
                    log.debug("deleting invite {} since party is full".format(invite_key))
                    pipe.delete(invite_key)
                    pipe.execute()
                    abort(http_client.CONFLICT, message="Party is full")

                pipe.watch(invite_key, accepting_player_party_key, sending_player_party_key, sending_player_invites_key)

                # If the inviting player is not in a party, form one now
                if sending_player_party_id is None:
                    sending_player_party_id = pipe.incr(party_id_key)
                    party_players_key = make_party_players_key(sending_player_party_id)
                    pipe.multi()
                    # Add inviting player to the new party
                    pipe.sadd(party_players_key, sending_player)
                    pipe.set(sending_player_party_key, sending_player_party_id)
                else:
                    party_players_key = make_party_players_key(int(sending_player_party_id))
                    pipe.multi()
                # Delete the invite
                log.debug("deleting invite {}".format(invite_key))
                pipe.delete(invite_key)
                pipe.zrem(sending_player_invites_key, invite_id)
                # Add invited player to the party
                pipe.sadd(party_players_key, accepting_player)
                pipe.set(accepting_player_party_key, sending_player_party_id)
                # Get all the members
                pipe.smembers(party_players_key)
                result = pipe.execute()
                return int(sending_player_party_id), [int(entry) for entry in result[-1]]
            except WatchError:
                pass

    abort(http_client.CONFLICT)


def get_player_party(player_id):
    scoped_player_party_key = make_player_party_key(player_id)
    party_id = g.redis.conn.get(scoped_player_party_key)
    return int(party_id) if party_id else party_id


def get_party_members(party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    return [int(member) for member in g.redis.conn.smembers(scoped_party_players_key)]


def set_player_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)
    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(scoped_party_players_key, scoped_player_party_key)
                current_party = pipe.get(scoped_player_party_key)
                if current_party == party_id:
                    return

                if pipe.sismember(scoped_party_players_key, player_id):
                    return

                pipe.multi()
                pipe.smembers(scoped_party_players_key)
                pipe.set(scoped_player_party_key, party_id)
                pipe.sadd(scoped_party_players_key, player_id)
                result = pipe.execute()
                return result[0]
            except WatchError:
                pass

    abort(http_client.CONFLICT)


def leave_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)
    sending_player_invites_key = make_player_invites_key(player_id)
    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(scoped_party_players_key, scoped_player_party_key)
                current_party = pipe.get(scoped_player_party_key)

                # Can't leave a party you're not a member of
                if current_party is None or int(current_party) != party_id:
                    abort(http_client.BAD_REQUEST, message="You're not a member of this party")

                # If the player has already left, do nothing
                if not pipe.sismember(scoped_party_players_key, player_id):
                    return

                outstanding_invites = pipe.zrange(sending_player_invites_key, 0, -1, withscores=True)
                pipe.multi()
                for invite_id, _ in outstanding_invites:
                    pipe.delete(make_party_invite_key(int(invite_id)))
                pipe.srem(scoped_party_players_key, player_id)
                pipe.delete(scoped_player_party_key)
                pipe.delete(sending_player_invites_key)
                result = pipe.execute()

                if result is None:
                    abort(http_client.BAD_REQUEST, message="You're not a member of this party")

                current_app.messagebus.publish_message("parties", {"event": "player_left", "player_id": player_id, "party_id": party_id})

                # Notify party members
                members = get_party_members(party_id)
                for member in members:
                    post_message("players", member, "party_notification",
                                 {
                                     "event": "player_left",
                                     "party_id": party_id,
                                     "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                                     "player_id": player_id,
                                     "player_url": url_for("players.entry", player_id=player_id, _external=True),
                                 })

                # Disband party if only one member is left
                if len(members) <= 1:
                    disband_party(party_id)
                    post_message("players", members[0], "party_notification",
                                 {
                                     "event": "disbanded",
                                     "party_id": party_id,
                                     "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                                 })

                return result

            except WatchError:
                pass

    abort(http_client.CONFLICT)


def disband_party(party_id):
    scoped_party_players_key = make_party_players_key(party_id)

    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(scoped_party_players_key)
                players = pipe.smembers(scoped_party_players_key)
                pipe.multi()
                for player in players:
                    pipe.delete(make_player_party_key(int(player)))
                pipe.delete(scoped_party_players_key)
                result = pipe.execute()
                return result
            except WatchError:
                pass

    abort(http_client.CONFLICT)


def create_party_invite(party_id, sending_player_id, invited_player_id):
    inviting_player_party_key = make_player_party_key(sending_player_id)
    invited_player_party_key = make_player_party_key(invited_player_id)
    scoped_invite_id_key = g.redis.make_key("party_invite:id:")
    sending_player_invites_key = make_player_invites_key(sending_player_id)
    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(invited_player_party_key)
                inviting_player_party_id = pipe.get(inviting_player_party_key)

                if inviting_player_party_id:
                    party_players_key = make_party_players_key(int(inviting_player_party_id))
                    pipe.watch(party_players_key)
                    members = get_party_members(inviting_player_party_id)
                    if len(members) >= get_max_players_per_party():
                        log.debug(f"Player {inviting_player_party_id} tried to invite to a party that was already full")
                        abort(http_client.BAD_REQUEST, message="Party is already full")

                    pipe.multi()
                    pipe.sismember(party_players_key, invited_player_id)
                    pipe.get(invited_player_party_key)
                    is_already_in_team, invited_player_party_id = pipe.execute()
                    pipe.watch(invited_player_party_key)
                    if is_already_in_team and invited_player_party_id == inviting_player_party_id:
                        log.debug("Player {} is already a member of party {}".format(invited_player_id, party_id))
                        return None

                invite_id = pipe.incr(scoped_invite_id_key)
                scoped_invite_key = make_party_invite_key(invite_id)
                pipe.multi()
                pipe.hset(scoped_invite_key, mapping={'from': sending_player_id, 'to': invited_player_id})
                pipe.zadd(sending_player_invites_key, mapping={invite_id: invited_player_id})
                pipe.execute()
                return invite_id
            except WatchError:
                pass

    abort(http_client.CONFLICT)


def get_party_invite(invite_id):
    scoped_party_invite_key = make_party_invite_key(invite_id)
    return g.redis.conn.hgetall(scoped_party_invite_key)


def decline_party_invite(invite_id, declining_player_id):
    scoped_party_invite_key = make_party_invite_key(invite_id)
    end = time() + OPERATION_TIMEOUT

    with g.redis.conn.pipeline() as pipe:
        while time() < end:
            try:
                pipe.watch(scoped_party_invite_key)

                # Get invite details
                invite = pipe.hgetall(scoped_party_invite_key)

                # Check there's an invite
                if not invite:
                    abort(http_client.NOT_FOUND)

                invite_sender_id = invite.get('from')
                invite_receiver_id = invite.get('to')
                if not invite_receiver_id:
                    log.debug("Party invite {} does not contain the invited player".format(invite_id))
                    abort(http_client.BAD_REQUEST, message="Inviting player doesn't match the invite")

                if int(invite_receiver_id) != declining_player_id:
                    log.debug("Party invite {} does not belong to the declining player".format(invite_id))
                    abort(http_client.FORBIDDEN, message="You can only decline invites to or from yourself")

                sending_player_invites_key = make_player_invites_key(int(invite_sender_id))
                pipe.multi()
                log.debug("deleting invite {}".format(scoped_party_invite_key))
                pipe.delete(scoped_party_invite_key)
                pipe.zrem(sending_player_invites_key, invite_id)
                pipe.execute()
                return int(invite_sender_id), int(invite_receiver_id)
            except WatchError:
                pass

    abort(http_client.CONFLICT)


def make_party_invite_key(invite_id):
    return g.redis.make_key("party_invite:{}:".format(invite_id))


def make_party_players_key(party_id):
    return g.redis.make_key("party:{}:players:".format(party_id))


def make_player_invites_key(player_id):
    return g.redis.make_key("player:{}:invites:".format(player_id))


def make_player_party_key(player_id):
    return g.redis.make_key("player:{}:party:".format(player_id))
