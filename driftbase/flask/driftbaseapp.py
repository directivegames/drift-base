"""
Flask app with gevent monkey patching.
"""
from gevent import monkey
monkey.patch_all()
from psycogreen.gevent import patch_psycopg
patch_psycopg()

import os

if os.environ.get('ENABLE_DATADOG_APM', '0') == '1':
    import ddtrace
    ddtrace.patch_all(logging=True)

if os.environ.get('ENABLE_DATADOG_METRICS', '0') == '1':
    from ddtrace.runtime import RuntimeMetrics
    RuntimeMetrics.enable()

from drift.flaskfactory import drift_app
app = drift_app()
