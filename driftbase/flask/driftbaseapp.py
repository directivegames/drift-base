"""
Flask app with gevent monkey patching.
"""
import gevent
from gevent import monkey
monkey.patch_all()
from psycogreen.gevent import patch_psycopg
patch_psycopg()

import os

if os.environ.get('ENABLE_DATADOG_APM', '0') == '1':
    import ddtrace
    ddtrace.patch_all(logging=True)

from drift.flaskfactory import drift_app
app = drift_app()

def foo():
    from driftconfig.util import get_default_drift_config
    from time import sleep
    while True:
        print("checking...")
        config = get_default_drift_config()
        print(config.get_table('tenants').find({'tenant_name': 'mw-tenant'}))
        sleep(2)

gevent.spawn_later(5, foo)
