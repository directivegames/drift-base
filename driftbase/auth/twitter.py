import os
import requests
import base64

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


class TwitterValidator(BaseOAuthValidator):
    def _get_details_fields(self) -> list[str]:
        return BaseOAuthValidator._get_details_fields(self) + ['code_verifier']
    
    def _call_oauth(self, client_id: str, client_secret: str, provider_details: dict) -> requests.Response:
        data = {
            'client_id': client_id,
            'grant_type': 'authorization_code',
            'code': provider_details['code'],
            'redirect_uri': provider_details['redirect_uri'],
            'code_verifier': provider_details['code_verifier']
        }
        headers = {
           'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()}'
        }
        return requests.post('https://api.twitter.com/2/oauth2/token', data=data, headers=headers)
            
    def _get_identity(self, access_token: str) -> requests.Response:
        return requests.get('https://api.twitter.com/2/users/me', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):
    provider_name = 'twitter'
    # expected auth_info
    '''
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
    validator = TwitterValidator(provider_name)
    '''
    validator.config = validator.config or {
        'client_id': os.environ.get('TWITTER_CLIENT_ID'),
        'client_secret': os.environ.get('TWITTER_CLIENT_SECRET')
    }
    '''
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
    '''
    {
        "data": {
            "id": "2364384500",
            "name": "Wang Hao",
            "username": "haowang1013"
        }
    }
    '''
    identity_id = identity['data']['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
