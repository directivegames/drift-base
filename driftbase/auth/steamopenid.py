import logging
import os
import requests
import re
from flask import request
from drift.blueprint import abort
import http.client as http_client
from werkzeug.exceptions import Unauthorized

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)

provider_name = 'steamopenid'


def authenticate(auth_info):
    '''
    Expect
    {
        'provider': 'steamopenid',
        'provider_details': <All the request params from the steam OpenID callback>
    }
    '''
    assert auth_info['provider'] == provider_name
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_steam_openid()
    username = "steam:" + identity_id
    return base_authenticate(username, "", True or automatic_account_creation)


def validate_steam_openid():
    '''
    validate steam OpenID and return the user id
    '''
    ob = request.get_json()
    provider_details = ob['provider_details']
    
    # Get the authentication config
    config = get_provider_config(provider_name)
    '''
    config = config or {
        'api_key': os.environ.get('STEAM_API_KEY')
    }
    '''    
    if not config:
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured for current tenant")        
    
    api_key = config.get('api_key')
    if not api_key:
        log.error('Steam OpenID cannot be validated, client_id or client_secret not configured')
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured correctly")
    
    data = provider_details
    data['openid.mode'] = 'check_authentication'
    for f in ['openid.claimed_id', 'openid.assoc_handle', 'openid.signed', 'openid.sig', 'openid.ns']:
        if f not in data:
            abort(http_client.BAD_REQUEST, description="Invalid provider details")    
    def abort_unauthorized(error):
        description = f'Steam OpenID validation failed. {error}'
        raise Unauthorized(description=description)

    # call oauth2 to get the access token
    try:
        r = requests.post('https://steamcommunity.com/openid/login', data=data)
        if 'is_valid:true' in r.text:
            steam_id = re.search(r'\d+$', provider_details['openid.claimed_id']).group(0)
        else:
            abort_unauthorized()
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Steam OpenID API status code: {r.status_code}')
    
    log.info(f"Steam player authenticated: {steam_id}")
    return steam_id
