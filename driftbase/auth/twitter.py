import logging
import os
import requests
import base64
from flask import request
from drift.blueprint import abort
import http.client as http_client
from werkzeug.exceptions import Unauthorized

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)

provider_name = 'twitter'


def authenticate(auth_info):
    '''
    Expect
    {
        'provider': 'twitter',
        'provider_details': {
            'code': <TWITTER_CODE>,
            'code_verifier': <TWITTER_CODE_VERIFIER>
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_twitter_code()
    username = "twitter:" + identity_id
    return base_authenticate(username, "", automatic_account_creation)


def validate_twitter_code():
    '''
    validate the twitter code and return the user id
    '''
    ob = request.get_json()
    provider_details = ob['provider_details']
    
    # Get the authentication config
    config = get_provider_config(provider_name)
    '''
    config = config or {
        'client_id': os.environ.get('TWITTER_CLIENT_ID'),
        'client_secret': os.environ.get('TWITTER_CLIENT_SECRET')
    }    
    '''
    if not config:
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured for current tenant")        
    
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')    
    if not client_id or not client_secret:
        log.error('Twitter code cannot be validated, client_id or client_secret not configured')
        abort(http_client.SERVICE_UNAVAILABLE, description=f"{provider_name} authentication not configured correctly")
    
    code = provider_details.get('code')
    redirect_uri = provider_details.get('redirect_uri')
    code_verifier = provider_details.get('code_verifier')
    if not code or not redirect_uri or not code_verifier:
        abort(http_client.BAD_REQUEST, description="Invalid provider details")

    def abort_unauthorized(error):
        description = f'Twitter code validation failed for client {client_id}. {error}'
        raise Unauthorized(description=description)

    # call oauth2 to get the access token
    try:
        data = {
            'client_id': client_id,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'code_verifier': code_verifier
        }
        headers = {
           'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()}'
        }
        r = requests.post('https://api.twitter.com/2/oauth2/token', data=data, headers=headers)
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Twitter oauth2 API status code: {r.status_code}')
    
    tokens = r.json()
    access_token = tokens['access_token']
    
    # get the user info from the access token
    try:
        user_info = requests.get('https://api.twitter.com/2/users/me', headers={
            'Authorization': f'Bearer {access_token}'
        }).json()
    except requests.exceptions.RequestException as e:
        abort_unauthorized(str(e))
    if r.status_code != 200:
        abort_unauthorized(f'Twitter users API status code: {r.status_code}')
    
    # Expect:
    '''
    {
        "data": {
            "id": "2364384500",
            "name": "Wang Hao",
            "username": "haowang1013"
    }
}
    '''
    log.info(f"Twitter user authenticated: {user_info}")
    return user_info['data']['id']
