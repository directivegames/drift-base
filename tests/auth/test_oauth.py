import unittest
from unittest import mock

import driftbase.auth.discord as discord
import driftbase.auth.twitter as twitter
import driftbase.auth.facebook as facebook
import driftbase.auth.google as google

from werkzeug.exceptions import HTTPException


all_providers = {
    "discord": discord,
    "twitter": twitter,
    "facebook": facebook,
    "google": google,
}


class TestOAuthValidate(unittest.TestCase):
    def setUp(self):
        self.valid_config = dict(client_id='client_id', client_secret='client_secret')
        self.valid_provider_details = dict(code='code', redirect_uri='redirect_uri')


    def test_fails_if_missing_or_incorrect_provider_name(self):
        for provider in all_providers.values():
            with self.assertRaises(KeyError):
                provider.authenticate(dict())
            with self.assertRaises(AssertionError):
                provider.authenticate(dict(provider=None))
            with self.assertRaises(AssertionError):
                provider.authenticate(dict(provider='foo'))


    def test_fails_with_invalid_configuration(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:
            # missing config
            config.return_value = None
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict()))
            
            # missing client_id
            config.return_value = dict(client_secret='')
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict()))

            # missing client_secret
            config.return_value = dict(client_id='')
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict()))


    def test_fails_with_invalid_provider_details(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:
            config.return_value = self.valid_config
            # missing provider details
            for name, provider in all_providers.items():
                with self.assertRaises(KeyError):
                    provider.authenticate(dict(provider=name))

            # empty details
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict()))

            # missing code
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict(redirect_uri='')))

            # missing redirect_uri
            for name, provider in all_providers.items():
                with self.assertRaises(HTTPException):
                    provider.authenticate(dict(provider=name, provider_details=dict(code='')))

            # missing code_verifier for twitter
            with self.assertRaises(HTTPException):
                twitter.authenticate(dict(provider='twitter', provider_details=self.valid_provider_details))


    def test_fails_with_invalid_oauth_response(self):
        with mock.patch('driftbase.auth.oauth.get_provider_config') as config:
            config.return_value = self.valid_config
            with mock.patch('driftbase.auth.oauth.BaseOAuthValidator.get_oauth_identity') as get_oauth_identity:
                # missing the 'id' key
                get_oauth_identity.return_value = {}
                for name, provider in all_providers.items():
                    with self.assertRaises(KeyError):
                        provider.authenticate(dict(provider=name, provider_details=self.valid_provider_details))

                # missing the 'data' key for twitter
                get_oauth_identity.return_value = {'id': '123'}
                with self.assertRaises(KeyError):
                    twitter.authenticate(dict(provider='twitter', provider_details=self.valid_provider_details))
                
    