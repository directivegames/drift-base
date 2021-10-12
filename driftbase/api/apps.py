import logging
from flask_smorest import Blueprint
from drift.core.extensions.urlregistry import Endpoints
from flask import g, current_app
from drift.utils import get_tier_name
from flask.views import MethodView

log = logging.getLogger(__name__)

bp = Blueprint(
    "apps", __name__, url_prefix="/apps", description="Other deployables running alongside drift-base on this tenant/tier"
)
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


#@bp.route("/", endpoint="app_roots")
#class AppRoots(MethodView):
#    pass

@endpoints.register
def endpoint_info(*args):
    # Add root endpoints of other deployables belonging to the tenant
    current_tier = get_tier_name()
    log.warning(f"INFO DUMP: AppRoots")
    this_app = current_app.config['name']
    log.warning(f"INFO DUMP: current app name: {this_app}")
    tenant = g.conf.tenant
    log.warning(f"INFO DUMP: tenant: {tenant}")
    app_roots = []
    ts = g.conf.table_store
    tenants_table = ts.get_table('tenants')
    tenants_content = tenants_table.find()
    log.warning(f"INFO DUMP: tenants: {tenants_content}")
    deployables_table = ts.get_table('deployables')
    deployables_content = deployables_table.find()
    log.warning(f"INFO DUMP: deployables: {deployables_content}")
    #deployables_content = deployables_table.find() #get_table('deployables').get({'deployable_name': deployable_name, 'tier_name': tier_name}),
    # deployables = tenants_table.find({"tier_name": tier_name, "tenant_name": })
    return {"app_roots": "justsometest"}
