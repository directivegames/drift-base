from abc import ABC, abstractmethod

import boto3
from aws_assume_role_lib import assume_role
from drift.core.extensions.driftconfig import get_tenant_config_value


class BotoClient(ABC):
    def __init__(self, region, tenant, service, role_config_resource=None, role_config_key=None):
        self.region = region
        self.tenant = tenant
        self.service = service
        self.role_config_resource = role_config_resource
        self.role_config_key = role_config_key
        client = self._clients_by_region.get((region, tenant))
        if client is None:
            session = self._sessions_by_region.get((region, tenant))
            if session is None:
                session = boto3.Session(region_name=self.region)
                role_to_assume = get_tenant_config_value(self.role_config_resource, self.role_config_key)
                if role_to_assume:
                    session = assume_role(session, role_to_assume)
                self._sessions_by_region[(region, tenant)] = session
            client = session.client(self.service)
            self._clients_by_region[(region, tenant)] = client

    def __getattr__(self, item):
        return getattr(self._clients_by_region[(self.region, self.tenant)], item)

    @property
    @abstractmethod
    def _sessions_by_region(self):
        raise NotImplementedError()

    @property
    @abstractmethod
    def _clients_by_region(self):
        raise NotImplementedError()
