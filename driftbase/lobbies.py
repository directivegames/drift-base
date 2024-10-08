import logging
import json
import typing
import random
import string
import datetime
import copy
from collections import defaultdict
from flask import g
from driftbase.models.db import CorePlayer
from driftbase.messages import post_message
from driftbase.utils.redis_utils import timeout_pipe, JsonLock
from driftbase.utils.exceptions import NotFoundException, UnauthorizedException, ConflictException, InvalidRequestException
from driftbase import flexmatch, parties
from redis.exceptions import WatchError

log = logging.getLogger(__name__)

MAX_LOBBY_ID_GENERATION_RETRIES = 100
LOBBY_ID_LENGTH = 6
DEFAULT_LOBBY_NAME = "Lobby"
LOBBY_MATCH_STARTING_LEAVE_LOCK_DURATION_SECONDS = 60
MAX_LOBBY_CUSTOM_DATA_BYTES = 4096


def get_player_lobby(player_id: int, expected_lobby_id: typing.Optional[str] = None):
    player_lobby_key = _get_player_lobby_key(player_id)

    lobby_id = g.redis.conn.get(player_lobby_key)

    if not lobby_id:
        log.info(f"Player '{player_id}' attempted to fetch a lobby without being a member of any lobby")
        message = f"Lobby {expected_lobby_id} not found" if expected_lobby_id else "No lobby found"
        raise NotFoundException(message)

    if expected_lobby_id and expected_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to fetch lobby '{expected_lobby_id}', but isn't a member of "
                    f"that lobby. Player is in lobby '{lobby_id}'")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(player_lobby_key):
            log.warning(f"Player '{player_id}' attempted to get lobby '{lobby_id}', but left the lobby "
                        f"while acquiring the lobby lock")
            raise ConflictException(f"You left the lobby while attempting to fetch it")

        lobby = lobby_lock.value

        if not lobby:
            log.warning(f"Player '{player_id}' is assigned to lobby '{lobby_id}' but the lobby doesn't exist")
            g.redis.conn.delete(player_lobby_key)
            raise NotFoundException("No lobby found")

        log.info(f"Returning lobby '{lobby_id}' for player '{player_id}'")

        # Sanity check that the player is a member of the lobby
        if not _get_lobby_member(lobby, player_id):
            log.error(f"Player '{player_id}' is supposed to be in lobby '{lobby_id}' but isn't a member of the lobby")
            g.redis.conn.delete(player_lobby_key)
            raise NotFoundException("No lobby found")

        return _get_personalized_lobby(lobby, player_id)


def create_lobby(player_id: int, team_capacity: int, team_names: list[str], lobby_name: typing.Optional[str],
                 map_name: typing.Optional[str], custom_data: typing.Optional[str]):
    # Check party
    if parties.get_player_party(player_id) is not None:
        log.warning(f"Failed to create lobby for player '{player_id}' due to player being in a party")
        raise InvalidRequestException(f"Cannot create a lobby while in a party")

    # Check matchmaking
    matchmaking_ticket = flexmatch.get_player_ticket(player_id)
    if matchmaking_ticket and matchmaking_ticket["Status"] not in flexmatch.EXPIRED_STATE:
        log.warning(f"Failed to create lobby for player '{player_id}' due to player having an active "
                    f"matchmaking ticket")
        raise InvalidRequestException(f"Cannot create a lobby while matchmaking")

    # Validate custom data
    if custom_data and _get_number_of_bytes(custom_data) > MAX_LOBBY_CUSTOM_DATA_BYTES:
        log.warning(f"Failed to create lobby for player '{player_id}' due to custom data exceeding "
                    f"'{MAX_LOBBY_CUSTOM_DATA_BYTES}' bytes")
        raise InvalidRequestException(f"Custom data too large. Maximum amount of bytes is {MAX_LOBBY_CUSTOM_DATA_BYTES}")

    player_lobby_key = _get_player_lobby_key(player_id)

    # Check existing lobby
    existing_lobby_id = g.redis.conn.get(player_lobby_key)
    if existing_lobby_id:
        log.info(f"Failed to create lobby for player '{player_id}' due to player being in lobby '{existing_lobby_id}'")
        raise InvalidRequestException(f"You cannot create a lobby while in another lobby")

    # Fetch player name
    player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

    # Create lobby
    for pipe in timeout_pipe():
        try:
            # Watch for changes in the player lobby key
            pipe.watch(player_lobby_key)

            for _ in range(MAX_LOBBY_ID_GENERATION_RETRIES):
                lobby_id = _generate_lobby_id()

                with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
                    if lobby_lock.value is not None:
                        log.info(f"Generated an existing lobby id. That's very unlucky (or lucky). Retrying...")
                        continue

                    log.info(f"Creating lobby '{lobby_id}' for player '{player_id}'")

                    new_lobby = {
                        "lobby_id": lobby_id,
                        "lobby_name": lobby_name or DEFAULT_LOBBY_NAME,
                        "map_name": map_name,
                        "team_capacity": team_capacity,
                        "team_names": team_names,
                        "create_date": datetime.datetime.utcnow().isoformat(),
                        "start_date": None,
                        "placement_date": None,
                        "status": "idle",
                        "custom_data": custom_data,
                        "members": [
                            {
                                "player_id": player_id,
                                "player_name": player_name,
                                "team_name": None,
                                "ready": False,
                                "host": True,
                                "join_date": datetime.datetime.utcnow().isoformat(),
                            }
                        ],
                    }

                    pipe.multi()
                    pipe.set(player_lobby_key, lobby_id)
                    lobby_lock.value = new_lobby

                    pipe.execute()

                    return new_lobby

            raise RuntimeError(f"Failed to generate unique lobby id for player '{player_id}'. "
                               f"Retried '{MAX_LOBBY_ID_GENERATION_RETRIES}' times")
        except WatchError as e:
            log.warning(f"Failed to create lobby for player '{player_id}'. "
                        f"Player lobby key value changed during lobby creation")
            raise ConflictException("You joined a lobby while creating a lobby")


def update_lobby(player_id: int, expected_lobby_id: str, team_capacity: typing.Optional[int], team_names: list[str],
                 lobby_name: typing.Optional[str], map_name: typing.Optional[str], custom_data: typing.Optional[str]):
    # Validate custom data
    if custom_data and _get_number_of_bytes(custom_data) > MAX_LOBBY_CUSTOM_DATA_BYTES:
        log.warning(f"Failed to update lobby for player '{player_id}' due to custom data exceeding "
                    f"'{MAX_LOBBY_CUSTOM_DATA_BYTES}' bytes")
        raise InvalidRequestException(f"Custom data too large. Maximum amount of bytes is "
                                      f"{MAX_LOBBY_CUSTOM_DATA_BYTES}")

    player_lobby_key = _get_player_lobby_key(player_id)

    lobby_id = g.redis.conn.get(player_lobby_key)

    if expected_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to update lobby '{expected_lobby_id}', but isn't a member of "
                    f"that lobby. Player is in lobby '{lobby_id}'")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(player_lobby_key):
            log.warning(f"Player '{player_id}' attempted to update lobby '{expected_lobby_id}', but left the lobby "
                        f"while acquiring the lobby lock")
            raise ConflictException(f"You left the lobby while attempting to update it")

        lobby = lobby_lock.value

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to update assigned lobby '{lobby_id}' but the lobby "
                        f"doesn't exist")
            g.redis.conn.delete(player_lobby_key)
            raise NotFoundException(f"Lobby {lobby_id} not found")

        host_player_id = _get_lobby_host_player_id(lobby)

        if host_player_id != player_id:
            log.warning(f"Player '{player_id}' attempted to update a lobby without being the lobby host")
            raise UnauthorizedException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can update "
                                        f"the lobby")

        # Prevent updating the lobby if the match has been initiated
        if _lobby_match_initiated(lobby):
            log.warning(f"Player '{player_id}' attempted to update lobby '{lobby_id}' which has initiated "
                        f"the lobby match")
            raise InvalidRequestException(f"Cannot update the lobby after the lobby match has been initiated")

        lobby_updated = False

        if team_capacity is not None:
            old_team_capacity = lobby["team_capacity"]

            if old_team_capacity != team_capacity:
                lobby_updated = True
                log.info(f"Host player '{player_id}' changed team capacity from '{old_team_capacity}' to "
                         f"'{team_capacity}' for lobby '{lobby_id}'")
                lobby["team_capacity"] = team_capacity

                # Go over members and enforce new team capacity
                team_counts = defaultdict(int)
                for member in lobby["members"]:
                    team_name = member["team_name"]
                    if team_name is not None:
                        current_team_count = team_counts[team_name]

                        if current_team_count < team_capacity:
                            team_counts[team_name] += 1
                        else:
                            log.info(f"Player '{player_id}' removed from team '{team_name}' due to team being over "
                                     f"capacity in lobby '{lobby_id}'")
                            member["team_name"] = None

        if team_names:
            old_team_names = lobby["team_names"]

            if old_team_names != team_names:
                lobby_updated = True
                log.info(f"Host player '{player_id}' changed team names from '{old_team_names}' to '{team_names}' "
                         f"for lobby '{lobby_id}'")
                lobby["team_names"] = team_names

                # Go over members and enforce new team names
                for member in lobby["members"]:
                    team_name = member["team_name"]
                    if team_name and team_name not in team_names:
                        log.info(f"Player '{player_id}' removed from team '{team_name}' due to now being an invalid "
                                 f"team in lobby '{lobby_id}'")
                        member["team_name"] = None

        if lobby_name:
            old_lobby_name = lobby["lobby_name"]

            if old_lobby_name != lobby_name:
                lobby_updated = True
                log.info(f"Host player '{player_id}' changed lobby name from '{old_lobby_name}' to '{lobby_name}' "
                         f"for lobby '{lobby_id}'")
                lobby["lobby_name"] = lobby_name

        if map_name:
            old_map_name = lobby["map_name"]

            if old_map_name != map_name:
                lobby_updated = True
                log.info(f"Host player '{player_id}' changed map name from '{old_map_name}' to '{map_name}' "
                         f"for lobby '{lobby_id}'")
                lobby["map_name"] = map_name

        if custom_data:
            old_custom_data = lobby["custom_data"]

            if old_custom_data != custom_data:
                lobby_updated = True
                log.info(f"Host player '{player_id}' changed custom data from '{old_custom_data}' to '{custom_data}' "
                         f"for lobby '{lobby_id}'")
                lobby["custom_data"] = custom_data

        if lobby_updated:
            lobby_lock.value = lobby

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby)
            _post_lobby_event_to_members(receiving_player_ids, "LobbyUpdated", lobby)


def delete_lobby(player_id: int, expected_lobby_id: str):
    player_lobby_key = _get_player_lobby_key(player_id)

    lobby_id = g.redis.conn.get(player_lobby_key)

    if not lobby_id:
        log.info(f"Player '{player_id}' attempted to delete a lobby without being a member of any lobby")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    if expected_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to delete lobby '{expected_lobby_id}', but isn't a member of "
                    f"that lobby. Player is in lobby '{lobby_id}'")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    _internal_delete_lobby(player_id, lobby_id)


def leave_lobby(player_id: int, expected_lobby_id: str):
    player_lobby_key = _get_player_lobby_key(player_id)

    lobby_id = g.redis.conn.get(player_lobby_key)

    if not lobby_id:
        log.info(f"Player '{player_id}' attempted to leave a lobby without being a member of any lobby")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    if expected_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to leave lobby '{expected_lobby_id}', but isn't a member of "
                    f"that lobby. Player is in lobby '{lobby_id}'")
        raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

    _internal_leave_lobby(player_id, lobby_id)

def join_lobby(player_id: int, lobby_id: str):
    player_lobby_key = _get_player_lobby_key(player_id)

    player_lobby_id = g.redis.conn.get(player_lobby_key)

    # Already a part of another lobby
    if player_lobby_id and player_lobby_id != lobby_id:
        log.info(f"Player '{player_id}' attempted to join lobby '{lobby_id}' while being a member in lobby "
                 f"'{player_lobby_id}'")
        raise InvalidRequestException(f"You cannot join a lobby while in another lobby")

    return _internal_join_lobby(player_id, lobby_id)


def update_lobby_member(player_id: int, member_id: int, lobby_id: str, team_name: typing.Optional[str],
                        ready: typing.Optional[bool]):
    player_lobby_key = _get_player_lobby_key(player_id)

    player_lobby_id = g.redis.conn.get(player_lobby_key)

    if player_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' without "
                    f"being in the lobby")
        raise UnauthorizedException(f"You don't have permission to access lobby {lobby_id}")

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(player_lobby_key):
            log.warning(f"Player '{player_id}' failed to update lobby '{lobby_id}' due to leaving the lobby while "
                        f"waiting for lobby lock")
            raise ConflictException(f"You left the lobby while updating the lobby")

        lobby = lobby_lock.value

        if player_id != member_id:
            host_player_id = _get_lobby_host_player_id(lobby)

            if player_id != host_player_id:
                log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' "
                            f"without being a the lobby host")
                raise UnauthorizedException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can update "
                                            f"other members")

            log.info(f"Host player '{player_id}' is updating member '{member_id}' in lobby '{lobby_id}'")

        # Prevent updating lobby member if the lobby match has been initiated
        if _lobby_match_initiated(lobby):
            log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' "
                        f"which has initiated the lobby match")
            raise InvalidRequestException(f"Cannot update lobby after the lobby match has been initialized")

        member_updated = False

        for member in lobby["members"]:
            if member["player_id"] != member_id:
                continue

            current_team = member["team_name"]

            if team_name and team_name not in lobby["team_names"]:
                log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' "
                            f"with invalid team name '{team_name}'")
                raise InvalidRequestException(f"Team name '{team_name}' is invalid")

            if current_team and team_name != current_team:
                log.info(f"Player '{player_id}' in lobby '{lobby_id}' left team '{current_team}'")
                member_updated = True
                ready = False

            if team_name and team_name != current_team and _can_join_team(lobby, team_name):
                log.info(f"Player '{player_id}' in lobby '{lobby_id}' joined team '{team_name}'")
                member_updated = True
                ready = False

            if not team_name:
                ready = False

            member["team_name"] = team_name

            if ready != member["ready"]:
                member_updated = True
                log.info(f"Player '{player_id}' in lobby '{lobby_id}' updated ready status to '{ready}'")

            member["ready"] = bool(ready)
            break

        if member_updated:
            lobby_lock.value = lobby

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby)
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberUpdated", {"lobby_id": lobby_id, "members":
                lobby["members"]})


def kick_member(player_id: int, member_id: int, lobby_id: str):
    player_lobby_key = _get_player_lobby_key(player_id)

    player_lobby_id = g.redis.conn.get(player_lobby_key)

    if player_lobby_id != lobby_id:
        log.warning(f"Player '{player_id}' attempted to kick member '{member_id}' in lobby '{lobby_id}' "
                    f"without being in the lobby")
        raise UnauthorizedException(f"You don't have permission to access lobby {lobby_id}")

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(player_lobby_key):
            log.warning(f"Player '{player_id}' failed to kick member '{member_id}' in lobby '{lobby_id}' due to "
                        f"leaving the lobby while waiting for lobby lock")
            raise ConflictException(f"You left the lobby while kicking the player")

        member_lobby_key = _get_player_lobby_key(member_id)

        member_lobby_id = g.redis.conn.get(member_lobby_key)

        if member_lobby_id != player_lobby_id:
            log.warning(f"Player '{player_id}' attempted to kick player '{member_id}' from lobby '{lobby_id}', but "
                        f"they aren't in the same lobby")
            raise InvalidRequestException(f"You and player {member_id} aren't in the same lobby")

        lobby = lobby_lock.value

        if not lobby:
            g.redis.conn.delete(player_lobby_key)
            g.redis.conn.delete(member_lobby_key)
            raise RuntimeError(f"Player '{player_id}' attempted to kick player '{member_id}' from lobby '{lobby_id}' "
                               f"which doesn't exist")

        host_player_id = _get_lobby_host_player_id(lobby)

        if player_id != host_player_id:
            log.warning(f"Player '{player_id}' attempted to kick member '{member_id}' from lobby '{lobby_id}' "
                        f"without being the lobby host")
            raise UnauthorizedException(f"You aren't the host of lobby {lobby_id}. "
                                        f"Only the lobby host can kick other members")

        current_length = len(lobby["members"])

        # Populate receiving player ids for message before kicking the player
        receiving_player_ids = _get_lobby_member_player_ids(lobby)

        # Remove player from members list
        lobby["members"] = [member for member in lobby["members"] if member["player_id"] != member_id]

        kicked = len(lobby["members"]) != current_length

        g.redis.conn.delete(member_lobby_key)

        if kicked:
            log.info(f"Host player '{player_id}' kicked member player '{member_id}' from lobby '{lobby_id}'")

            lobby_lock.value = lobby

            # Notify members and kicked player
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberKicked", {"lobby_id": lobby_id,
                                                                                     "kicked_player_id": member_id,
                                                                                     "members": lobby["members"]})
        else:
            log.warning(f"Host player '{player_id}' tried to kick member player '{member_id}' from lobby "
                        f"'{lobby_id}', but '{member_id}' wasn't a member of the lobby")


# Helpers

def _internal_join_lobby(player_id: int, lobby_id: str) -> dict:
    player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

    player_lobby_key = _get_player_lobby_key(player_id)

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        current_lobby_id = g.redis.conn.get(player_lobby_key)
        if current_lobby_id and lobby_id != current_lobby_id:
            log.warning(f"Player '{player_id}' failed to join lobby '{lobby_id}' due to joining lobby "
                        f"'{current_lobby_id}' while waiting for lobby lock")
            raise ConflictException(f"You joined lobby {current_lobby_id} while attempting to join lobby {lobby_id}")

        lobby = lobby_lock.value

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to join lobby '{lobby_id}' which doesn't exist")
            raise NotFoundException(f"Lobby {lobby_id} doesn't exist")

        if not _get_lobby_member(lobby, player_id):
            lobby["members"].append({
                "player_id": player_id,
                "player_name": player_name,
                "team_name": None,
                "ready": False,
                "host": False,
                "join_date": datetime.datetime.utcnow().isoformat(),
            })

            lobby_lock.value = lobby

            g.redis.conn.set(player_lobby_key, lobby_id)

            log.info(f"Player '{player_id}' joined lobby '{lobby_id}'")

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberJoined", {"lobby_id": lobby_id,
                                                                                     "members": lobby["members"]})
        else:
            log.info(f"Player '{player_id}' attempted to join lobby '{lobby_id}' while already being a member")

        return _get_personalized_lobby(lobby, player_id)


def _get_personalized_lobby(lobby: dict, player_id: int) -> dict:
    # Add personalized connection options if the match has started
    if _lobby_match_initiated(lobby) and lobby.get("connection_string", None):
        # TODO: Think about where this code should reside since it's match and GameLift specific

        player_lobby = copy.deepcopy(lobby)

        # Default to spectator
        connection_options = "SpectatorOnly=1"

        member = _get_lobby_member(lobby, player_id)

        if member["team_name"]:
            # Player is a part of a team. Ensure the player has a player session
            player_session_id = _ensure_player_session(lobby, player_id, member)
            if player_session_id:
                connection_options = f"PlayerSessionId={player_session_id}?PlayerId={player_id}"

        player_lobby["connection_options"] = connection_options
        return player_lobby

    return lobby


def _ensure_player_session(lobby: dict, player_id: int, member: dict) -> typing.Optional[str]:
    from driftbase import match_placements

    lobby_id = lobby["lobby_id"]
    placement_id = lobby.get("placement_id", None)

    if not placement_id:
        raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. "
                           f"Lobby has no placement id")

    with JsonLock(match_placements._get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not placement:
            raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. "
                               f"No placement exists for placement id '{placement_id}'")

        game_session_arn = placement.get("game_session_arn", None)

        if not game_session_arn:
            raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. "
                               f"No game session arn exists for placement id '{placement_id}'")

        # Check if the game session is still valid
        game_sessions = flexmatch.describe_game_sessions(GameSessionId=game_session_arn)
        if len(game_sessions["GameSessions"]) == 0:
            log.warning(f"Unable to ensure a player session for player '{player_id}' in lobby '{lobby_id}'. "
                        f"Game session '{game_session_arn}' not found. "
                        f"Assuming the game session has been deleted/cleaned up")
            return None

        game_session = game_sessions["GameSessions"][0]
        game_session_status = game_session["Status"]
        if game_session_status not in ("ACTIVE", "ACTIVATING"):
            log.warning(f"Unable to ensure a player session for player '{player_id}' in lobby '{lobby_id}'. "
                        f"Game session '{game_session_arn}' is in status '{game_session_status}'")
            return None

        # Check if player has a valid player session
        player_sessions = flexmatch.describe_player_sessions(GameSessionId=game_session_arn)
        for player_session in player_sessions["PlayerSessions"]:
            if player_session["PlayerId"] == str(player_id) and player_session["Status"] in ("RESERVED", "ACTIVE"):
                return player_session["PlayerSessionId"]

        # Create new player session since no valid one was found
        response = flexmatch.create_player_session(
            GameSessionId=game_session_arn,
            PlayerId=str(player_id),
            PlayerData=json.dumps({
                "player_name": member["player_name"],
                "team_name": member["team_name"],
                "host": member["host"],
            }),
        )

        return response["PlayerSession"]["PlayerSessionId"]


def _internal_leave_lobby(player_id: int, lobby_id: str):
    player_lobby_key = _get_player_lobby_key(player_id)

    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(player_lobby_key):
            log.warning(f"Player '{player_id}' failed to leave lobby '{lobby_id}'"
                        f" due to leaving the lobby while waiting for lobby lock")
            raise ConflictException(f"You left the lobby while attempting leave it")

        lobby = lobby_lock.value

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to leave lobby '{lobby_id}' which doesn't exist")
            raise NotFoundException(f"Lobby {lobby_id} doesn't exist")

        if lobby["status"] == "starting":
            placement_date = datetime.datetime.fromisoformat(lobby["placement_date"])
            now = datetime.datetime.utcnow()

            duration = (now - placement_date).total_seconds()

            if duration > LOBBY_MATCH_STARTING_LEAVE_LOCK_DURATION_SECONDS:
                log.warning(f"Player '{player_id}' is leaving lobby '{lobby_id}'"
                            f" which has been starting the lobby match for '{duration}' seconds. "
                            f"Allowing the player to leave. Lobby may be borked")
            else:
                log.warning(f"Player '{player_id}' attempted to leave lobby '{lobby_id}'"
                            f" while the lobby match is starting")
                raise InvalidRequestException(f"Cannot leave the lobby while the lobby match is starting. "
                                              f"You can leave after "
                                              f"{LOBBY_MATCH_STARTING_LEAVE_LOCK_DURATION_SECONDS - duration} seconds")

        current_length = len(lobby["members"])
        host_player_id = _get_lobby_host_player_id(lobby)

        # Remove player from members list
        lobby["members"] = [member for member in lobby["members"] if member["player_id"] != player_id]
        left = len(lobby["members"]) != current_length

        if left:
            log.info(f"Lobby member player '{player_id}' left lobby '{lobby_id}'")
            if lobby["members"]:
                # Promote new host if the host left
                if host_player_id == player_id:
                    # Host left the lobby, select the oldest member as host
                    sorted_members = sorted(lobby["members"],
                                            key=lambda m: datetime.datetime.fromisoformat(m["join_date"]))
                    sorted_members[0]["host"] = True
                    new_host_player_id = sorted_members[0]["player_id"]
                    log.info(f"Player {new_host_player_id} promoted to lobby host for lobby '{lobby_id}'")
                    lobby["members"] = sorted_members

                lobby_lock.value = lobby

                # Notify remaining members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberLeft", {"lobby_id": lobby_id,
                                                                                       "left_player_id": player_id,
                                                                                       "members": lobby["members"]})
            else:
                # No one left in the lobby, delete the lobby
                log.info(f"No one left in lobby '{lobby_id}'. Lobby deleted.")
                lobby_lock.value = None
        else:
            log.warning(f"Lobby member player '{player_id}' attempted to leave lobby '{lobby_id}'"
                        f" without being a member")

        g.redis.conn.delete(player_lobby_key)


def _internal_delete_lobby(player_id: int, lobby_id: str):
    with JsonLock(_get_lobby_key(lobby_id)) as lobby_lock:
        if lobby_id != g.redis.conn.get(_get_player_lobby_key(player_id)):
            log.warning(f"Player '{player_id}' failed to delete lobby '{lobby_id}'"
                        f" due to leaving the lobby while waiting for lobby lock")
            raise ConflictException(f"You left the lobby while attempting to delete it")

        lobby = lobby_lock.value

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to delete lobby '{lobby_id}' which doesn't exist")
            return

        host_player_id = _get_lobby_host_player_id(lobby)

        if host_player_id != player_id:
            log.warning(f"Player '{player_id}' attempted to delete lobby '{lobby_id}' without being the host")
            raise UnauthorizedException(f"You aren't the host of lobby {lobby_id}."
                                        f" Only the lobby host can delete the lobby")

        log.info(f"Lobby host player '{player_id}' deleted lobby '{lobby_id}'")

        for member in lobby["members"]:
            if not member["host"]:
                g.redis.conn.delete(_get_player_lobby_key(member["player_id"]))

        # Delete the lobby
        lobby_lock.value = None

        # Notify members
        receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
        if receiving_player_ids: # Potentially empty if the host is alone in the lobby
            _post_lobby_event_to_members(receiving_player_ids, "LobbyDeleted", {"lobby_id": lobby_id})


def _lobby_match_initiated(lobby: dict) -> bool:
    return lobby["status"] in ("starting", "started")


def _can_join_team(lobby: dict, team: str) -> bool:
    team_count = 0
    team_capacity = lobby["team_capacity"]
    for member in lobby["members"]:
        team_name = member["team_name"]
        if team_name == team:
            team_count += 1

    return team_count < team_capacity


def _get_lobby_member(lobby: dict, player_id: int) -> typing.Optional[dict]:
    return next((member for member in lobby["members"] if member["player_id"] == player_id), None)


def _generate_lobby_id() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=LOBBY_ID_LENGTH))


def _get_lobby_key(lobby_id: str) -> str:
    return g.redis.make_key(f"lobby:{lobby_id}:")


def _get_player_lobby_key(player_id: int) -> str:
    return g.redis.make_key(f"player:{player_id}:lobby:")


def _get_lobby_host_player_id(lobby: dict) -> int:
    for member in lobby["members"]:
        if member["host"]:
            return member["player_id"]

    return 0


def _get_lobby_member_player_ids(lobby: dict, exclude_player_ids: typing.Optional[list[int]] = None) -> list[int]:
    if exclude_player_ids is None:
        exclude_player_ids = []

    return [member["player_id"] for member in lobby["members"] if member["player_id"] not in exclude_player_ids]


def _post_lobby_event_to_members(receiving_player_ids: list[int], event: str, event_data: typing.Optional[dict] = None,
                                 expiry: typing.Optional[int] = None):
    """ Insert an event into the 'lobby' queue of the 'players' exchange. """
    log.info(f"Posting '{event}' to players '{receiving_player_ids}' with event_data '{event_data}'")

    if not receiving_player_ids:
        log.warning(f"Empty receiver in lobby event '{event}' message")
        return

    payload = {
        "event": event,
        "data": event_data or {}
    }

    for receiver_id in receiving_player_ids:
        post_message("players", int(receiver_id), "lobby", payload, expiry, sender_system=True)


def _get_number_of_bytes(s: str) -> int:
    return len(s.encode('utf-8'))