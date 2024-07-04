"""
Flexmatch configuration - shamelessly lifted from the parties resource configuration
"""

import logging

log = logging.getLogger(__name__)

FLEXMATCH_DEFAULTS = {
    "aws_gamelift_role": "",
    "valid_regions": ["eu-west-1"],
    "max_rejoin_time_seconds": 90,
    "backfill_ticket_pattern": "^BackFill--.*",  # This is highly tenant specific; Perseus/TMA server issues backfill tickets with this prefix, but there's no rule here"""
    "matchmaker_ban_times": {
        "DG-Ranked": {
            "match_types": ["EMatchType::Ranked"],
            "ban_time_seconds": [
                6 * 60,
                15 * 60,
                30 * 60,
                60 * 60,
                12 * 60 * 60],
            "expiry_seconds": 24 * 60 * 60
        }
    }
}

def drift_init_extension(app, **kwargs):
    pass


def register_deployable(ts, deployablename, attributes):
    """
    Deployable registration callback.
    'deployablename' is from table 'deployable-names'.
    """
    pass


def register_deployable_on_tier(ts, deployable, attributes):
    """
    Deployable registration callback for tier.
    'deployable' is from table 'deployables'.
    """
    pass


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    pass


def register_deployable_on_tenant(
        ts, deployable_name, tier_name, tenant_name, resource_attributes
):
    pass
