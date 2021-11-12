import logging
import string
import random
import datetime
import typing
from flask import g
from driftbase.utils.redis_utils import JsonLock, timeout_pipe
from driftbase.exceptions.drift_api_exceptions import NotFoundException, ConflictException, ForbiddenException
from driftbase.models.db import Friendship
from redis.exceptions import WatchError

log = logging.getLogger(__name__)

MAX_FRIEND_CODE_GENERATION_RETRIES = 100
FRIEND_CODE_LENGTH = 6
FRIEND_CODE_DURATION_SECONDS = 10 * 60

def get_player_friend_code(player_id: int) -> dict:
    player_friend_code_key = _get_player_friend_code_key(player_id)

    friend_code_id = g.redis.conn.get(player_friend_code_key)

    if not friend_code_id:
        log.info(f"Player '{player_id}' attempted to fetch their friend code without having one")
        raise NotFoundException("No friend code found")

    with JsonLock(_get_friend_code_key(friend_code_id)) as friend_code_lock:
        if friend_code_id != g.redis.conn.get(player_friend_code_key):
            log.warning(f"Player '{player_id}' attempted to get friend code '{friend_code_id}', but was no longer assigned to it while acquiring the lock")
            raise ConflictException(f"You lost the friend code while attempting to fetch it")

        friend_code = friend_code_lock.value

        if not friend_code:
            log.warning(f"Player '{player_id}' is assigned to friend code '{friend_code_id}' but the friend code doesn't exist")
            g.redis.conn.delete(player_friend_code_key)
            raise NotFoundException("No friend code found")

        log.info(f"Returning friend code '{friend_code_id}' for player '{player_id}'")

        return friend_code

def get_friend_code(friend_code_id: str) -> dict:
    with JsonLock(_get_friend_code_key(friend_code_id)) as friend_code_lock:
        friend_code = friend_code_lock.value

        if not friend_code:
            raise NotFoundException("Friend code not found")

        return friend_code

def create_friend_code(player_id: int) -> dict:
    player_friend_code_key = _get_player_friend_code_key(player_id)

    # Check existing friend code
    existing_friend_code_id = g.redis.conn.get(player_friend_code_key)
    if existing_friend_code_id:
        log.info(f"Player '{player_id}' attempted to create a friend code while assigned to an existing friend code")
        return get_player_friend_code(player_id)

    for _ in range(MAX_FRIEND_CODE_GENERATION_RETRIES):
        friend_code_id = _generate_friend_code_id()

        with JsonLock(_get_friend_code_key(friend_code_id)) as friend_code_lock:
            if friend_code_lock.value is not None:
                log.info(f"Generated an existing friend code. That's very unlucky (or lucky). Retrying...")
                continue

        # Create friend code
        for pipe in timeout_pipe():
            try:
                # Watch for changes in the player friend code key
                pipe.watch(player_friend_code_key)

                for _ in range(MAX_FRIEND_CODE_GENERATION_RETRIES):
                    friend_code_id = _generate_friend_code_id()

                    with JsonLock(_get_friend_code_key(friend_code_id), ttl=FRIEND_CODE_DURATION_SECONDS) as friend_code_lock:
                        if friend_code_lock.value is not None:
                            log.info(f"Generated an existing friend code. That's very unlucky (or lucky). Retrying...")
                            continue

                        log.info(f"Creating friend code '{friend_code_id}' for player '{player_id}'. Valid for '{FRIEND_CODE_DURATION_SECONDS}' seconds")

                        create_date = datetime.datetime.utcnow()
                        expiry_date = create_date + datetime.timedelta(seconds=FRIEND_CODE_DURATION_SECONDS)

                        new_friend_code = {
                            "friend_code": friend_code_id,
                            "player_id": player_id,
                            "create_date": create_date.isoformat(),
                            "expiry_date": expiry_date.isoformat(),
                        }

                        pipe.multi()
                        pipe.set(player_friend_code_key, friend_code_id, ex=FRIEND_CODE_DURATION_SECONDS)
                        friend_code_lock.value = new_friend_code

                        pipe.execute()

                        return new_friend_code

                raise RuntimeError(f"Failed to generate unique friend code id for player '{player_id}'. Retried '{MAX_FRIEND_CODE_GENERATION_RETRIES}' times")
            except WatchError as e:
                log.warning(f"Failed to create friend code for player '{player_id}'. Player friend code key value changed during friend code creation")
                raise ConflictException("You were assigned a friend code while creating the friend code")

def use_friend_code(player_id: int, friend_code_id: str) -> typing.Tuple[int, int]:
    with JsonLock(_get_friend_code_key(friend_code_id)) as friend_code_lock:
        friend_code = friend_code_lock.value

        if not friend_code:
            raise NotFoundException("Friend code not found")

        friend_code_player_id: int = friend_code["player_id"]

        left_id = player_id
        right_id = friend_code_player_id

        if left_id == right_id:
            raise ForbiddenException("You cannot use your own friend code")

        if left_id > right_id:
            left_id, right_id = right_id, left_id

        existing_friendship = g.db.query(Friendship).filter(
            Friendship.player1_id == left_id,
            Friendship.player2_id == right_id
        ).first()
        if existing_friendship is not None:
            friendship = existing_friendship
            if friendship.status == "deleted":
                friendship.status = "active"
            else:
                raise ConflictException("You are already friends with this player")
        else:
            friendship = Friendship(player1_id=left_id, player2_id=right_id)
            g.db.add(friendship)

        g.db.commit()

        return friend_code_player_id, friendship.id

# Helpers

def _get_player_friend_code_key(player_id: int) -> str:
    return g.redis.make_key(f"player:{player_id}:friend-code:")

def _get_friend_code_key(friend_code_id: str) -> str:
    return g.redis.make_key(f"friend-code:{friend_code_id}:")

def _generate_friend_code_id() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=FRIEND_CODE_LENGTH))
