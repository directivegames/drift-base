import logging
from datetime import datetime, timedelta, timezone

import prometheus_client
from drift.core.resources.postgres import connect
from drift.utils import get_tier_name
from driftconfig.util import get_drift_config
from prometheus_client import make_wsgi_app
from prometheus_client.metrics_core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import select, distinct, cast, Date
from sqlalchemy.sql.functions import count
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from driftbase.config import DEFAULT_CLIENT_HEARTBEAT_TIMEOUT_SECONDS
from driftbase.models.db import tbl_client, tbl_user, tbl_user_identity

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
        """
        Return a description of the various metrics.

        Returning descriptions separately from collect helps ensure
        that the collect logic is not run before it's ready.
        """
        yield self._make_users_gauge()
        yield self._make_clients_gauge()
        yield self._make_identities_gauge()
        yield self._make_daily_active_users_gauge()
        yield self._make_weekly_active_users_gauge()
        yield self._make_monthly_active_users_gauge()
        yield self._make_rolling_weekly_active_users_gauge()
        yield self._make_rolling_monthly_active_users_gauge()

    def collect(self):
        """
        Iterate over all tenants and generate whatever metrics are desired.
        """
        tier_name = get_tier_name()
        config = self._get_drift_config()
        tenants = config.table_store.get_table('tenants')
        tenant_rows = tenants.find(
            {'tier_name': tier_name, 'deployable_name': self.deployable_name, 'state': 'active'}
        )
        users = self._make_users_gauge()
        clients = self._make_clients_gauge()
        identities = self._make_identities_gauge()
        daily_active_users = self._make_daily_active_users_gauge()
        weekly_active_users = self._make_weekly_active_users_gauge()
        monthly_active_users = self._make_monthly_active_users_gauge()
        rolling_daily_active_users = self._make_rolling_daily_active_users_gauge()
        rolling_weekly_active_users = self._make_rolling_weekly_active_users_gauge()
        rolling_monthly_active_users = self._make_rolling_monthly_active_users_gauge()
        for tenant in tenant_rows:
            postgres_config = tenant.get('postgres')
            if postgres_config:
                # FIXME: Creating the engine each time is not really efficient, but since it happens
                #        relatively seldom, a few times per minute at most, optimising it is not urgent.
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

                with db_engine.begin() as conn:
                    identities_and_types = conn.execute(
                        select(tbl_user_identity.c.identity_type, count(tbl_user_identity.c.identity_type)).where(
                            tbl_user_identity.c.user_id.isnot(None)).group_by(
                            tbl_user_identity.c.identity_type)
                    ).all()
                for entry in identities_and_types:
                    identities.add_metric([tier_name, tenant['tenant_name'], entry.identity_type], entry.count)

                now = datetime.now(timezone.utc)

                for period, gauge in {'day': daily_active_users, 'week': weekly_active_users,
                                      'month': monthly_active_users}.items():
                    days_since_period_start = now.weekday() if period == 'week' else now.day - 1 if period == 'month' else 0
                    period_start = (now - timedelta(days=days_since_period_start)).date()
                    with db_engine.begin() as conn:
                        logins_and_types = conn.execute(
                            select(tbl_user_identity.c.identity_type, count(distinct(tbl_user.c.user_id)))
                            .join(tbl_user, tbl_user_identity.c.user_id == tbl_user.c.user_id)
                            .where(tbl_user_identity.c.user_id.isnot(None))
                            .where(cast(tbl_user_identity.c.logon_date, Date()) >= period_start)
                            .group_by(tbl_user_identity.c.identity_type)
                        ).all()
                    for entry in logins_and_types:
                        gauge.add_metric([tier_name, tenant['tenant_name'], entry.identity_type], entry.count)

                for period, gauge in {1: rolling_daily_active_users, 7: rolling_weekly_active_users,
                                      30: rolling_monthly_active_users}.items():
                    period_start = now - timedelta(days=period)
                    with db_engine.begin() as conn:
                        logins_and_types = conn.execute(
                            select(tbl_user_identity.c.identity_type, count(distinct(tbl_user.c.user_id)))
                            .join(tbl_user, tbl_user_identity.c.user_id == tbl_user.c.user_id)
                            .where(tbl_user_identity.c.user_id.isnot(None))
                            .where(tbl_user_identity.c.logon_date >= period_start)
                            .group_by(tbl_user_identity.c.identity_type)
                        ).all()
                    for entry in logins_and_types:
                        gauge.add_metric([tier_name, tenant['tenant_name'], entry.identity_type], entry.count)

        yield users
        yield clients
        yield identities
        yield daily_active_users
        yield weekly_active_users
        yield monthly_active_users
        yield rolling_daily_active_users
        yield rolling_weekly_active_users
        yield rolling_monthly_active_users

    def _make_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_users",
            "Number of users registered with a tenant",
            labels=["tier", "tenant"]
        )

    def _make_clients_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_clients",
            "Number of clients for a tenant with an active heartbeat",
            labels=["tier", "tenant"]
        )

    def _make_identities_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_identities",
            "Number of identities for a tenant attached to a user",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_daily_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_calendar_daily_active_users",
            "Number of active users for a tenant by calendar day",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_weekly_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_calendar_weekly_active_users",
            "Number of active users for a tenant by calendar week",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_monthly_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_calendar_monthly_active_users",
            "Number of active users for a tenant by calendar month",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_rolling_daily_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_rolling_daily_active_users",
            "Number of active users for a tenant rolling by 24 previous hours",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_rolling_weekly_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_rolling_weekly_active_users",
            "Number of active users for a tenant rolling by 7 days",
            labels=["tier", "tenant", "identity_type"]
        )

    def _make_rolling_monthly_active_users_gauge(self):
        return GaugeMetricFamily(
            f"{self.metric_prefix}_rolling_monthly_active_users",
            "Number of active users for a tenant rolling by 30 days",
            labels=["tier", "tenant", "identity_type"]
        )

    def _get_drift_config(self):
        conf = get_drift_config(
            tier_name=get_tier_name(),
            deployable_name=self.deployable_name,
        )
        return conf
