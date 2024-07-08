import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator

provider_name = 'google'

class GoogleValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)


    def _call_oauth(self, provider_details: dict) -> requests.Response:
        data = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'code': provider_details['code'],
            'redirect_uri': provider_details['redirect_uri'],
            'grant_type': 'authorization_code'
        }
        return requests.post('https://oauth2.googleapis.com/token', data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })


    def _get_identity(self, response: requests.Response, provider_details: dict) -> requests.Response | dict:
        access_token = response.json()['access_token']
        return requests.get('https://www.googleapis.com/oauth2/v1/userinfo', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):    
    # expected auth_info
    '''    
    {
        'provider': 'google',
        'provider_details': {
            'code': <GOOGLE_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = GoogleValidator()
    '''
    validator.config = validator.config or {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID'),
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET')
    }
    '''
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
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
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
