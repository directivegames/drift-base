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

provider_name = 'discord'


def authenticate(auth_info):
    '''
    Expect
    {
        'provider': 'discord',
        'provider_details': {
            'code': <DISCORD_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_discord_code()
    username = "discord:" + identity_id
    return base_authenticate(username, "", automatic_account_creation)


def validate_discord_code():
    '''
    validate the discord code and return the user id
    '''
    ob = request.get_json()
    provider_details = ob['provider_details']
    
    # Get the authentication config
    config = get_provider_config(provider_name)
    '''
    config = config or {
        'client_id': os.environ.get('DISCORD_CLIENT_ID'),
        'client_secret': os.environ.get('DISCORD_CLIENT_SECRET')
    }
    '''
    if not config:
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured for current tenant")        
    
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')
    if not client_id or not client_secret:
        log.error('Discord code cannot be validated, client_id or client_secret not configured')
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured correctly")
    
    code = provider_details.get('code')
    redirect_uri = provider_details.get('redirect_uri')
    if not code or not redirect_uri:
        abort(http_client.BAD_REQUEST, description="Invalid provider details")

    def abort_unauthorized(error):
        description = f'Discord code validation failed for client {client_id}. {error}'
        raise Unauthorized(description=description)

    # call oauth2 to get the access token
    try:
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'scope': 'identify'
        }
        r = requests.post('https://discord.com/api/oauth2/token', data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Discord oauth2 API status code: {r.status_code}')
    
    tokens = r.json()
    access_token = tokens['access_token']
    
    # get the user info from the access token
    try:
        user_info = requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f'Bearer {access_token}'
        }).json()
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Discord users API status code: {r.status_code}')
    
    # Expect:
    '''
    {
        "accent_color": null,
        "avatar": null,
        "avatar_decoration_data": null,
        "banner": null,
        "banner_color": null,
        "clan": null,
        "discriminator": "0",
        "flags": 0,
        "global_name": "wanghao",
        "id": "120900197248139266",
        "locale": "en-US",
        "mfa_enabled": true,
        "premium_type": 0,
        "public_flags": 0,
        "username": "wanghao9256"
    }
    '''
    log.info(f"Discord user authenticated: {user_info}")
    return user_info['id']
