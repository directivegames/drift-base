import os
import requests
import base64

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator

provider_name = 'twitter'

class TwitterValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)


    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        self._abort_unauthorized('token validation not implemented')
        '''
        access_token = provider_details['token']
        return requests.get('https://api.twitter.com/2/users/me', headers={
            'Authorization': f'Bearer {access_token}'
        })
        '''        


def authenticate(auth_info):    
    # expected auth_info
    '''
    {
        'provider': 'twitter',
        'provider_details': {
            'token': <TWITTER_ACCESS_TOKEN>            
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = TwitterValidator()
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
    '''
    {
        "data": {
            "id": "XXX",
            "name": "XXX",
            "username": "XXX"
        }
    }
    '''
    identity_id = identity['data']['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
