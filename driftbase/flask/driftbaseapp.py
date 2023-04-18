"""
Flask app with gevent monkey patching.
"""

# Always patch_all first
from gevent import monkey
monkey.patch_all()

# Additionally patch psycopg
from psycogreen.gevent import patch_psycopg
patch_psycopg()

from drift.flaskfactory import drift_app

app = drift_app()
