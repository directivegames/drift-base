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
bp = Blueprint("client_config", __name__, url_prefix="/client_config")
endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


class ClientConfigResponse(ma.Schema):
    config_name = ma.fields.Str(required=True)
    value = ma.fields.Str(required=True, default="")


class ClientConfigsResponse(ma.Schema):
    client_configs = ma.fields.Nested(
        ClientConfigResponse, many=True, metadata=dict(description='Function controls'))


@bp.route("", endpoint="configs")
class ClientConfigAPI(MethodView):

    @bp.response(http_client.OK, ClientConfigsResponse)
    def get(self):
        # TODO: This might need to be changed to just check one specific config key, depending on if we want to hide
        # the other switches for whatever reason
        log.info(f"Returning function controls of tenant {get_tenant_name()}")

        tenant_client_config = _get_client_config()
        output = []
        for config_key, config_val in tenant_client_config.items():
            output_entry = {
                "config_name": config_key,
                "value": config_val
            }
            output.append(output_entry)

        return {"client_configs": output}


@endpoints.register
def endpoint_info(*args):
    ret = {
        "client_config": url_for("client_config.configs", _external=True),
    }
    return ret


def _get_client_config():
    return g.conf.tenant.get("client_configs", CLIENT_CONFIGS_DEFAULTS)
