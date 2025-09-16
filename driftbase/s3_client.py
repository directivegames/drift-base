from driftbase.boto_client import BotoClient


class S3Client(BotoClient):
    __sessions_by_region = {}
    __clients_by_region = {}

    def __init__(self, region, tenant):
        super().__init__(region, tenant, 's3', 'cdn', 'aws_cdn_role')

    @property
    def _clients_by_region(self):
        return self.__class__.__clients_by_region

    @property
    def _sessions_by_region(self):
        return self.__class__.__sessions_by_region
