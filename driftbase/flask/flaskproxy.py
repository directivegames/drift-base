from typing import Any
import flask
from werkzeug.local import LocalProxy
from drift.core.resources.redis import RedisCache
from sqlalchemy.orm import Session

class _flaskProxy:
    """
    Proxy which allows type hinting flask globals. Import instead of
    flask.g to benefit  from type hints.
    """

    # Note: Some of these are actually 'LocalProxy[T]', but for improved type hinting we will hint the underlying type.
    redis : RedisCache
    db : Session

    def __getattr__(self, key):
        return getattr(flask.g, key)
    def __setattr__(self, name: str, value: Any) -> None:
        flask.g.__setattr__(name, value)

g = _flaskProxy()
