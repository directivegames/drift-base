"""
Flask app with gevent monkey patching.
"""

from gevent import monkey
monkey.patch_module("threading")  # noqa: E402

from drift.flaskfactory import drift_app  # Do this first for gevent monkey patching
import os

# Optionally enable Metrics
if os.environ.get('ENABLE_DATADOG_METRICS', '0') == '1':
    from ddtrace.runtime import RuntimeMetrics
    RuntimeMetrics.enable()

# Optionally enable APM
if os.environ.get('ENABLE_DATADOG_APM', '0') == '1':
    import ddtrace
    ddtrace.patch_all(logging=True)

app = drift_app()
