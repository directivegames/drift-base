import http.client as http_client
import logging
import marshmallow as ma
from flask.views import MethodView
from flask import url_for

from driftbase.utils.tenant import get_tenant_name
from drift.core.extensions.urlregistry import Endpoints
from drift.blueprint import Blueprint
from collections import defaultdict

from flask import g

CLIENT_CONFIGS_DEFAULTS = defaultdict(str)  # str default constructor is empty string

log = logging.getLogger(__name__)
bp = Blueprint("client_configs", __name__, url_prefix="/client_configs")
endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


class ClientConfigsResponse(ma.Schema):
    client_configs = ma.fields.Dict(keys=ma.fields.Str(), values=ma.fields.Str(),
                                    metadata=dict(description='Client configs'))


@bp.route("", endpoint="configs")
class ClientConfigAPI(MethodView):
    no_jwt_check = ["GET"]

    @bp.response(http_client.OK, ClientConfigsResponse)
    def get(self):
        log.info(f"Returning client configs of tenant {get_tenant_name()}")
        tenant_client_config = _get_client_configs()
        return {"client_configs": tenant_client_config}


@endpoints.register
def endpoint_info(*args):
    ret = {
        "client_configs": url_for("client_configs.configs", _external=True),
    }
    return ret


def _get_client_configs():
    return g.conf.tenant.get("client_configs", CLIENT_CONFIGS_DEFAULTS)
