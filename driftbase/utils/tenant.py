from flask import g


def get_tenant_name():
    return g.conf.tenant["tenant_name"]
