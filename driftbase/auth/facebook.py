import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


class FacebookValidator(BaseOAuthValidator):
    def _call_oauth(self, client_id: str, client_secret: str, provider_details: dict) -> requests.Response:
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': provider_details['redirect_uri'],
            'code': provider_details['code']
        }
        return requests.get('https://graph.facebook.com/v12.0/oauth/access_token', params=data)
            
    def _get_identity(self, access_token: str) -> requests.Response:
        return requests.get('https://graph.facebook.com/me', params={
            'fields': 'id',
            'access_token': access_token})


def authenticate(auth_info):
    provider_name = 'facebook'
    # expected auth_info
    '''
    {
        'provider': 'facebook',
        'provider_details': {
            'code': <FACEBOOK_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = FacebookValidator(provider_name)
    '''
    validator.config = validator.config or {
        'client_id': os.environ.get('FACEBOOK_CLIENT_ID'),
        'client_secret': os.environ.get('FACEBOOK_CLIENT_SECRET')
    }
    '''
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
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
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
