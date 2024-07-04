import logging
import os
import requests
from flask import request
from drift.blueprint import abort
import http.client as http_client
from werkzeug.exceptions import Unauthorized

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)

provider_name = 'facebook'


def authenticate(auth_info):
    '''
    Expect
    {
        'provider': 'facebook',
        'provider_details': {
            'code': <FACEBOOK_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_facebook_code()
    username = "facebook:" + identity_id
    return base_authenticate(username, "", automatic_account_creation)


def validate_facebook_code():
    '''
    validate the facebook code and return the user id
    '''
    ob = request.get_json()
    provider_details = ob['provider_details']
    
    # Get the authentication config
    config = get_provider_config(provider_name)
    '''
    config = config or {
        'client_id': os.environ.get('FACEBOOK_CLIENT_ID'),
        'client_secret': os.environ.get('FACEBOOK_CLIENT_SECRET')
    }
    '''
    if not config:
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured for current tenant")        
    
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')
    if not client_id or not client_secret:
        log.error('Facebook code cannot be validated, client_id or client_secret not configured')
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured correctly")
    
    code = provider_details.get('code')
    redirect_uri = provider_details.get('redirect_uri')
    if not code or not redirect_uri:
        abort(http_client.BAD_REQUEST, description="Invalid provider details")

    def abort_unauthorized(error):
        description = f'Facebook code validation failed for client {client_id}. {error}'
        raise Unauthorized(description=description)

    # call oauth2 to get the access token
    try:
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'code': code
        }
        r = requests.get('https://graph.facebook.com/v12.0/oauth/access_token', params=data)
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Facebook oauth API status code: {r.status_code}')
    
    tokens = r.json()
    access_token = tokens['access_token']
    
    # get the user info from the access token
    try:
        user_info = requests.get('https://graph.facebook.com/me', params={
            'fields': 'id',
            'access_token': access_token
        }).json()
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Facebook graph API status code: {r.status_code}')
    
    # Expect:
    '''
    {
        "id": "1493137904628843",
        "name": "Wang Hao",
        "picture": {
            "data": {
                "height": 50,
                "is_silhouette": false,
                "url": "https://platform-lookaside.fbsbx.com/platform/profilepic/?asid=1493137904628843&height=50&width=50&ext=1722674771&hash=AbaI-rOldXwhtiF9h3a0CVim",
                "width": 50
            }
        }
    }
    '''
    log.info(f"Google user authenticated: {user_info}")
    return user_info['id']
