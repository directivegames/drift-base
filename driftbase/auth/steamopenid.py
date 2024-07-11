import requests
import re
import marshmallow as ma

from .authenticate import authenticate as base_authenticate
from .oauth import BaseOAuthValidator


provider_name = 'steamopenid'


class SteamOpenIDDetailsSchema(ma.Schema):
    assoc_handle = ma.fields.String(data_key='openid.assoc_handle', required=True, allow_none=False)
    claimed_id = ma.fields.String(data_key='openid.claimed_id', required=True, allow_none=False)
    identity = ma.fields.String(data_key='openid.identity', required=True, allow_none=False)
    ns = ma.fields.String(data_key='openid.ns', required=True, allow_none=False)
    op_endpoint = ma.fields.String(data_key='openid.op_endpoint', required=True, allow_none=False)
    response_nonce = ma.fields.String(data_key='openid.response_nonce', required=True, allow_none=False)
    return_to = ma.fields.String(data_key='openid.return_to', required=True, allow_none=False)
    signed = ma.fields.String(data_key='openid.signed', required=True, allow_none=False)
    sig = ma.fields.String(data_key='openid.sig', required=True, allow_none=False)
    


class SteamOpenIDValidator(BaseOAuthValidator):
    def __init__(self):
        super().__init__(name=provider_name, details_schema=SteamOpenIDDetailsSchema)
    

    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        data = provider_details
        data['openid.mode'] = 'check_authentication'
        r = requests.post('https://steamcommunity.com/openid/login', data=data)
    
        if 'is_valid:true' in r.text:
            steam_id = re.search(r'\d+$', provider_details['openid.claimed_id']).group(0)
            return {'id': steam_id}
        else:
            self._abort_unauthorized(f'OAuth response is not valid: {r.text}')


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
    identity = validator.get_oauth_identity(auth_info['provider_details'])
    identity_id = identity['id']
    # Do not use 'provider_name' in the username, needs to be consistent with steam.py
    username = f'steam:{identity_id}'
    return base_authenticate(username, '', automatic_account_creation=auth_info.get('automatic_account_creation', True))
