import logging
from datetime import datetime, timedelta

import prometheus_client
from drift.core.resources.postgres import connect
from drift.utils import get_tier_name
from driftconfig.util import get_drift_config
from prometheus_client import make_wsgi_app
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import select
from sqlalchemy.sql.functions import count
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from driftbase.config import DEFAULT_CLIENT_HEARTBEAT_TIMEOUT_SECONDS
from driftbase.models.db import tbl_client, tbl_user

log = logging.getLogger(__name__)


_registered = False

def drift_init_extension(app, **kwargs):
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {'/metrics': make_wsgi_app()})

    try:
        prometheus_client.REGISTRY.unregister(prometheus_client.GC_COLLECTOR)
        prometheus_client.REGISTRY.unregister(prometheus_client.PLATFORM_COLLECTOR)
        prometheus_client.REGISTRY.unregister(prometheus_client.PROCESS_COLLECTOR)
    except KeyError:
        log.error("No prometheus collector registered")

    global _registered
    if not _registered:
        prometheus_client.REGISTRY.register(MetricsCollector(app))
        _registered = True


class MetricsCollector(Collector):

    def __init__(self, app):
        self.app = app
        self.deployable_name = app.config.get('name')
        self.metric_prefix = f"{self.deployable_name.replace('-', '_')}"

    def describe(self):
        yield self._make_users_gauge()
        yield self._make_clients_gauge()

    def collect(self):
        tier_name = get_tier_name()
        config = self._get_drift_config()
        tenants = config.table_store.get_table('tenants')
        tenant_rows = tenants.find(
            {'tier_name': tier_name, 'deployable_name': self.deployable_name, 'state': 'active'}
        )
        users = self._make_users_gauge()
        clients = self._make_clients_gauge()
        for tenant in tenant_rows:
            postgres_config = tenant.get('postgres')
            if postgres_config:
                db_engine = connect(postgres_config)
                with db_engine.begin() as conn:
                    num_users = conn.execute(
                        select(count(tbl_user.c.user_id)).where(tbl_user.c.status == 'active')
                    ).scalar_one()
                users.add_metric([tier_name, tenant['tenant_name'].replace('-', '_')], num_users)
                with db_engine.begin() as conn:
                    num_clients = conn.execute(
                        select(count(tbl_client.c.client_id)).where(tbl_client.c.status == 'active').where(
                            tbl_client.c.heartbeat > datetime.utcnow() - timedelta(
                                seconds=DEFAULT_CLIENT_HEARTBEAT_TIMEOUT_SECONDS))
                    ).scalar_one()
                clients.add_metric([tier_name, tenant['tenant_name'].replace('-', '_')], num_clients)
        yield users
        yield clients

    def _make_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_users",
            "Number of users registered with a tenant",
            labels=["tier", "tenant"]
        )

    def _make_clients_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_clients",
            "Number of clients in tenant",
            labels=["tier", "tenant"]
        )

    def _get_drift_config(self):
        conf = get_drift_config(
            tier_name=get_tier_name(),
            deployable_name=self.deployable_name,
        )
        return conf
