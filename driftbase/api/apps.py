import logging
from flask_smorest import Blueprint
from drift.core.extensions.urlregistry import Endpoints
from flask import g, url_for

log = logging.getLogger(__name__)

bp = Blueprint(
    "apps", __name__, url_prefix="/apps", description="Other deployables running alongside drift-base on this tenant/tier"
)
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


@endpoints.register
def endpoint_info(*args):
    # Add root endpoints of other deployables belonging to the tenant
    tenant_me = g.conf.tenant
    tier_me = tenant_me["tier_name"]
    deployable_me = tenant_me["deployable_name"]
    tenant_name = tenant_me["tenant_name"]
    tenant_table = g.conf.table_store.get_table("tenants")
    my_url = url_for("root.root", _external=True)
    my_target = tenant_me.get("apitarget", {}).get("api", None)
    log.warning(f"INFO DUMP: I'm {deployable_me} on {tenant_name}/{tier_me} with url {my_url}, looking for companion apps.")
    app_targets = {}
    if my_target:
        for deployable in tenant_table.find({"tenant_name": tenant_name, "tier_name": tier_me}):
            deployable_name = deployable["deployable_name"]
            if deployable_name == deployable_me:
                continue
            deployable_target = deployable.get("apitarget", {}).get("api", None)
            log.warning(f"INFO DUMP: I've found {deployable_name} with api target {deployable_target}.")
            if deployable_target is None:
                continue
            deployable_url = my_url.replace(my_target, deployable_target)  # HACK
            app_targets[deployable_name] = deployable_url
    return {"app_roots": app_targets}
