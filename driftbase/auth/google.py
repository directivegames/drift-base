import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator

provider_name = 'google'

class GoogleValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)


    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        access_token = provider_details['token']
        return requests.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):    
    # expected auth_info
    '''    
    {
        'provider': 'google',
        'provider_details': {
            'token': <GOOGLE_ACCESS_TOKEN>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = GoogleValidator()
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
    '''
    {
        "email": "XXX",
        "family_name": "XXX",
        "given_name": "XXX",
        "hd": "XXX",
        "id": "XXX",
        "name": "XXX",
        "picture": "XXX",
        "verified_email": true
    }
    '''
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
