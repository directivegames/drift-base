import logging

from driftconfig.util import get_parameters

log = logging.getLogger(__file__)


TIER_DEFAULTS = {
    "repository": "<PLEASE FILL IN>",  # Example: directive-tiers.dg-api.com
    "revision": "<PLEASE FILL IN>",   # Example: static-data,
    "allow_client_pin": False
}


# NOTE THIS IS DEPRECATED AND NEEDS TO BE UPGRADED TO NU STYLE PROVISIONING LOGIC
def provision(config, args, recreate=False):
    params = get_parameters(config, args, TIER_DEFAULTS.keys(), "static_data")

    # Static data repo is per product
    if 'static_data_defaults' not in config.product:
        config.product['static_data_defaults'] = params

    # Create entry for this tenant
    config.tenant['staticdata'] = config.product['static_data_defaults']


def healthcheck():
    pass
