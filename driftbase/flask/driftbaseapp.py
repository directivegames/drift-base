"""
Flask app with gevent monkey patching.
"""
try:
    from gevent import monkey
    monkey.patch_module("threading")  # noqa: E402
except ImportError:
    print(f"Failed to patch 'threading' module with gevent monkey patching")

from drift.flaskfactory import drift_app  # Do this first for gevent monkey patching

app = drift_app()
