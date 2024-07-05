import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


class DiscordValidator(BaseOAuthValidator):
    def _call_oauth(self, client_id: str, client_secret: str, provider_details: dict) -> requests.Response:
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': provider_details['code'],
            'redirect_uri': provider_details['redirect_uri'],
            'grant_type': 'authorization_code',            
            'scope': 'identify'
        }
        return requests.post('https://discord.com/api/oauth2/token', data=data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })
        
    def _get_identity(self, access_token: str) -> requests.Response:
        return requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):
    provider_name = 'discord'    
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
    validator = DiscordValidator(provider_name)
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
