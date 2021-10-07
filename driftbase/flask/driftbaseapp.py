"""
Flask app with gevent monkey patching.
"""
from gevent import monkey
from typing import Union

monkey.patch_all()
from psycogreen.gevent import patch_psycopg

patch_psycopg()

import os


def as_bool(value: Union[str, bool, None]) -> bool:
    if value is None:
        return False

    if isinstance(value, bool):
        return value

    return value.lower() in ('true', '1')


if as_bool(os.environ.get('ENABLE_DATADOG_PROFILING', False)):
    import ddtrace.profiling.auto  # noqa: F401

if as_bool(os.environ.get('ENABLE_DATADOG_APM', False)):
    from ddtrace import patch_all

    patch_all(logging=True)

from drift.flaskfactory import drift_app

app = drift_app()
