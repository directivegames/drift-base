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

provider_name = 'google'


def authenticate(auth_info):
    '''
    Expect
    {
        'provider': 'google',
        'provider_details': {
            'code': <GOOGLE_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_google_code()
    username = "google:" + identity_id
    return base_authenticate(username, "", automatic_account_creation)


def validate_google_code():
    '''
    validate the google code and return the user id
    '''
    ob = request.get_json()
    provider_details = ob['provider_details']
    
    # Get the authentication config
    config = get_provider_config(provider_name)
    '''
    config = config or {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID'),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET')
    }
    '''
    if not config:
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured for current tenant")        
    
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')
    if not client_id or not client_secret:
        log.error('Google code cannot be validated, client_id or client_secret not configured')
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured correctly")
    
    code = provider_details.get('code')
    redirect_uri = provider_details.get('redirect_uri')
    if not code or not redirect_uri:
        abort(http_client.BAD_REQUEST, description="Invalid provider details")

    def abort_unauthorized(error):
        description = f'Google code validation failed for client {client_id}. {error}'
        raise Unauthorized(description=description)

    # call oauth2 to get the access token
    try:
        data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        r = requests.post('https://oauth2.googleapis.com/token', data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Google oauth2 API status code: {r.status_code}')
    
    tokens = r.json()
    access_token = tokens['access_token']
    
    # get the user info from the access token
    try:
        user_info = requests.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={
            'Authorization': f'Bearer {access_token}'
        }).json()
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Google userinfo API status code: {r.status_code}')
    
    # Expect:
    '''
    {
        "email": "wanghao@directivegames.com",
        "family_name": "Wang",
        "given_name": "Hao",
        "hd": "directivegames.com",
        "id": "102949216487512835220",
        "name": "Hao Wang",
        "picture": "https://lh3.googleusercontent.com/a/ACg8ocK_Ol4i_3X81Lo2ABpm4X2odtwnt2jaTdYGovG0tHAlZzvu7w=s96-c",
        "verified_email": true
    }
    '''
    log.info(f"Google user authenticated: {user_info}")
    return user_info['id']
