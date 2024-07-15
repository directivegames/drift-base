import os
import requests

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


provider_name = 'discord'

class DiscordValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name)
    

    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        access_token = provider_details['token']
        return requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f'Bearer {access_token}'
        })


def authenticate(auth_info):    
    # expected auth_info
    '''
    {
        'provider': 'discord',
        'provider_details': {
            'token': <DISCORD_ACCESS_TOKEN>
        }
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = DiscordValidator()
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
        "global_name": "XXX",
        "id": "XXX",
        "locale": "en-US",
        "mfa_enabled": true,
        "premium_type": 0,
        "public_flags": 0,
        "username": "XXX"
    }
    '''
    identity_id = identity['id']
    username = f'{provider_name}:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get("automatic_account_creation", True))
