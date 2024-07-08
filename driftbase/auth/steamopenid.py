import logging
import os
import requests
import re

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


provider_name = 'steamopenid'

class SteamOpenIDValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name, config_fields=['api_key'], details_fields=['openid.claimed_id', 'openid.assoc_handle', 'openid.signed', 'openid.sig', 'openid.ns'])
    

    def _call_oauth(self, provider_details: dict) -> requests.Response:
        data = provider_details
        data['openid.mode'] = 'check_authentication'
        return requests.post('https://steamcommunity.com/openid/login', data=data)


    def _get_identity(self, response: requests.Response, provider_details: dict) -> requests.Response | dict:
        if 'is_valid:true' in response.text:
            steam_id = re.search(r'\d+$', provider_details['openid.claimed_id']).group(0)
            return {'id': steam_id}
        else:
            self._abort_unauthorized(f'OAuth response is not valid: {response.text}')


def authenticate(auth_info):
    # expected auth_info
    '''
    {
        'provider': 'steamopenid',
        'provider_details': <All the request params from the steam OpenID callback>
    }
    '''
    assert auth_info['provider'] == provider_name
    validator = SteamOpenIDValidator()
    '''    
    validator.config = validator.config or {
        'api_key': os.environ.get('STEAM_API_KEY')
    }
    '''
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    identity_id = identity['id']
    # Do not use 'provider_name' in the username, needs to be consistent with steam.py
    username = f'steam:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get('automatic_account_creation', True))
