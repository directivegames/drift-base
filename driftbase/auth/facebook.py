import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator

provider_name = 'facebook'

class FacebookValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)


    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        access_token = provider_details['token']
        return requests.get('https://graph.facebook.com/me', params={
            'fields': 'id',
            'access_token': access_token})


def authenticate(auth_info):    
    # expected auth_info
    '''
    {
        'provider': 'facebook',
        'provider_details': {
            'token': <FACEBOOK_ACCESS_TOKEN>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = FacebookValidator()
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
    '''
    {
        "id": "XXX",
        "name": "XXX",
        "picture": {
            "data": {
                "height": 50,
                "is_silhouette": false,
                "url": "XXX",
                "width": 50
            }
        }
    }
    '''
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
