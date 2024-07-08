import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


provider_name = 'discord'

class DiscordValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)
    

    def _call_oauth(self, provider_details: dict) -> requests.Response:
        data = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'code': provider_details['code'],
            'redirect_uri': provider_details['redirect_uri'],
            'grant_type': 'authorization_code',            
            'scope': 'identify'
        }
        return requests.post('https://discord.com/api/oauth2/token', data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })


    def _get_identity(self, response: requests.Response, provider_details: dict) -> requests.Response | dict:
        access_token = response.json()['access_token']
        return requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):    
    # expected auth_info
    '''
    {
        'provider': 'discord',
        'provider_details': {
            'code': <DISCORD_CODE>,
            'redirect_uri': <REDIRECT_URI>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = DiscordValidator()
    '''    
    validator.config = validator.config or {
        'client_id': os.environ.get('DISCORD_CLIENT_ID'),
        'client_secret': os.environ.get('DISCORD_CLIENT_SECRET')
    }
    '''
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    # expected identity
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
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
