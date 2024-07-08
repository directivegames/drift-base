import unittest
from unittest import mock

import driftbase.auth.discord as discord
import driftbase.auth.twitter as twitter
import driftbase.auth.facebook as facebook
import driftbase.auth.google as google
import driftbase.auth.steamopenid as steamopenid

from werkzeug.exceptions import HTTPException


class TestOAuthValidate(unittest.TestCase):
    def setUp(self):
        common_config = dict(client_id='client_id', client_secret='client_secret')
        common_details = dict(code='code', redirect_uri='redirect_uri')
        self.all_providers = {
            'discord': dict(module=discord, valid_config=common_config, valid_details=common_details),
            'twitter': dict(module=twitter, valid_config=common_config, valid_details={**common_details, **dict(code_verifier='code_verifier')}),
            'facebook': dict(module=facebook, valid_config=common_config, valid_details=common_details),
            'google': dict(module=google, valid_config=common_config, valid_details=common_details),
            'steamopenid': dict(module=steamopenid, valid_config=dict(api_key='api_key'), valid_details={
                'openid.claimed_id': 'openid.claimed_id',
                'openid.assoc_handle': 'openid.assoc_handle',
                'openid.signed': 'openid.signed',
                'openid.sig': 'openid.sig',
                'openid.ns': 'openid.ns',
            }),
        }


    def test_fails_if_missing_or_incorrect_provider_name(self):
        for elem in self.all_providers.values():
            provider = elem['module']
            with self.assertRaises(KeyError):
                provider.authenticate(dict())
            with self.assertRaises(AssertionError):
                provider.authenticate(dict(provider=None))
            with self.assertRaises(AssertionError):
                provider.authenticate(dict(provider='foo'))


    def test_fails_with_invalid_configuration(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:                        
            for name, elem in self.all_providers.items():
                # missing config
                config.return_value = None
                provider = elem['module']
                with self.assertRaises(HTTPException):                    
                    provider.authenticate(dict(provider=name, provider_details=dict()))
                
                # missing one config key
                for k in elem['valid_config'].keys():
                    invalid_config = elem['valid_config'].copy()
                    del invalid_config[k]
                    config.return_value = invalid_config                    
                    with self.assertRaises(HTTPException):
                        provider.authenticate(dict(provider=name, provider_details=dict()))

    
    def test_fails_with_invalid_provider_details(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:
            for name, elem in self.all_providers.items():
                # use valid config
                config.return_value = elem['valid_config']
                provider = elem['module']

                # missing provider details
                with self.assertRaises(KeyError):
                    provider.authenticate(dict(provider=name))
            
                # empty details
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict()))

                # missing one detail field
                for k in elem['valid_details'].keys():
                    invalid_details = elem['valid_details'].copy()
                    del invalid_details[k]
                    with self.assertRaises(HTTPException):
                        provider.authenticate(dict(provider=name, provider_details=invalid_details))
    

    def test_fails_with_invalid_oauth_response(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:            
            with mock.patch('driftbase.auth.oauth.BaseOAuthValidator.get_oauth_identity') as get_oauth_identity:
                for name, elem in self.all_providers.items():
                    # use valid config
                    config.return_value = elem['valid_config']
                    provider = elem['module']

                    # missing the 'id' key
                    get_oauth_identity.return_value = {}                
                    with self.assertRaises(KeyError):
                        provider.authenticate(dict(provider=name, provider_details=elem['valid_details']))

                    # missing the 'data' key for twitter
                    if name == 'twitter':
                        get_oauth_identity.return_value = {'id': '123'}
                        with self.assertRaises(KeyError):
                            provider.authenticate(dict(provider=name, provider_details=elem['valid_details']))
