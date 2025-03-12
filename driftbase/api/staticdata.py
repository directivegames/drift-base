import json
import logging
import os
from http.client import SERVICE_UNAVAILABLE

import marshmallow as ma
from drift.blueprint import Blueprint
from drift.blueprint import abort
from drift.core.extensions.urlregistry import Endpoints
from flask import g, url_for, jsonify
from flask.views import MethodView

from driftbase.s3_client import S3Client

log = logging.getLogger(__file__)

bp = Blueprint('staticdata', __name__, url_prefix='/staticdata')
endpoints = Endpoints()


def _get_tenant_name():
    return g.conf.tenant.get('tenant_name')


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


#
# Expected config:
#
# tier: {
#     staticdata: {
#         index_root: S3_INDEX_URL,
#         cdn_list: [
#             ('name', EXTERNAL_DATA_URL),
#         ],
#     },
# }
# tenant: {
#     staticdata: {
#         repository: "ORGANIZATION/PRODUCT",
#         ref: "refs/heads/BRANCH_OR_TAG",
#         allow_client_pin: False,
#     },
# }
#

def get_static_data_ids():
    data = g.conf.tenant.get('staticdata')
    if data:
        origin = "Tenant config"
        repo = data['repository']
        return {repo: (data, origin)}
    else:
        return {}


class StaticDataGetQuerySchema(ma.Schema):
    static_data_ref = ma.fields.String(metadata=dict(description="A GIT reference tag to get a particular version"))


@bp.route('', endpoint='list')
class StaticDataAPI(MethodView):
    no_jwt_check = ['GET']

    @bp.arguments(StaticDataGetQuerySchema, location='query')
    def get(self, args):
        """
        Returns server side config that the client needs
        """
        data = {}

        def get_from_url(url):
            content = g.redis.get(url)
            if content:
                return json.loads(content)

            with g.redis.lock("lock" + url):
                content = g.redis.get(url)
                if content:
                    return json.loads(content)
                s3 = S3Client(os.environ.get('AWS_REGION'), _get_tenant_name())
                bucket, key = url.split('/', 3)[2:]
                response = s3.get_object(Bucket=bucket, Key=key)
                content = response['Body'].read().decode('utf-8')
                g.redis.set(url, content, expire=50)
                return json.loads(content)

        data["static_data_urls"] = []

        tier = g.conf.tier
        cdn_config = tier.get('staticdata', {})
        cdn_index_root = cdn_config.get('index_root')
        if not cdn_index_root:
            log.error("No 'index_root' specified in tier config for static_data")
            abort(SERVICE_UNAVAILABLE, description="No 'index_root' specified in tier config for static_data")

        for repository, (ref_entry, origin) in get_static_data_ids().items():

            # Get the index file from S3 and index it by 'ref'
            index_file_url = "{}{}/index.json".format(cdn_index_root, repository)
            err = None
            try:
                index_file = get_from_url(index_file_url)
            except Exception as e:
                err = "Can't fetch %s: %s" % (index_file_url, e)
                log.exception(err)
            if err:
                data["error"] = err
                continue
            index_file = {ref_entry["ref"]: ref_entry for ref_entry in index_file["index"].get("commits", [])}

            # Use this ref if it matches
            ref = index_file.get(ref_entry["revision"])

            # Override if client is pinned to a particular version
            if ref_entry.get("allow_client_pin", False) and args.get('static_data_ref') in index_file:
                ref = index_file[args.get('static_data_ref')]
                origin = "Client pin"

            def make_data_url(root_url, repository, ref):
                if not root_url.endswith('/'):
                    root_url += '/'
                return '{}{}/data/{}/'.format(root_url, repository, ref)

            if ref:
                d = {
                    "repository": repository,
                    "revision": ref["ref"],
                    "commit_id": ref["commit_id"],
                    "origin": origin,
                    "cdn_list": [
                        {'cdn': cdn,
                         'data_root_url': make_data_url(root_url, repository, ref["commit_id"]),
                         }
                        for cdn, root_url in cdn_config.get('cdn_list', [])
                    ],
                }
                # legacy single-cdn entry
                if len(d["cdn_list"]):
                    # add the first configured url
                    d["data_root_url"] = d["cdn_list"][0]["data_root_url"]

                data["static_data_urls"].append(d)

        return jsonify(data)


@endpoints.register
def endpoint_info(current_users):
    return {
        "static_data": url_for("staticdata.list", _external=True),
    }
