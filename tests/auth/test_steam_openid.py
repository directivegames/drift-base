import unittest
from unittest import mock

import driftbase.auth.steamopenid as steamopenid

from werkzeug.exceptions import HTTPException


class TestSteamOpenIDValidate(unittest.TestCase):
    def setUp(self):
        self.valid_config = dict(api_key='api_key')
        self.valid_provider_details = {}
        for f in ['openid.claimed_id', 'openid.assoc_handle', 'openid.signed', 'openid.sig', 'openid.ns']:
            self.valid_provider_details[f] = f


    def test_fails_if_missing_or_incorrect_provider_name(self):
        with self.assertRaises(KeyError):
            steamopenid.authenticate(dict())
        with self.assertRaises(AssertionError):
            steamopenid.authenticate(dict(provider=None))
        with self.assertRaises(AssertionError):
            steamopenid.authenticate(dict(provider='foo'))


    def test_fails_with_invalid_configuration(self):
        with mock.patch('driftbase.auth.steamopenid.get_provider_config') as config:
            # missing config
            config.return_value = None
            with self.assertRaises(HTTPException):
                steamopenid.authenticate(dict(provider='steamopenid', provider_details=dict()))
            
            # missing api_key
            config.return_value = dict()
            with self.assertRaises(HTTPException):
                steamopenid.authenticate(dict(provider='steamopenid', provider_details=dict()))


    def test_fails_with_invalid_provider_details(self):
        with mock.patch('driftbase.auth.steamopenid.get_provider_config') as config:
            config.return_value = self.valid_config
            # missing provider details
            with self.assertRaises(KeyError):
                steamopenid.authenticate(dict(provider='steamopenid'))

            # empty details
            with self.assertRaises(HTTPException):
                steamopenid.authenticate(dict(provider='steamopenid', provider_details=dict()))

            # details missing required fields
            for f in self.valid_provider_details.keys():
                provider_details = self.valid_provider_details.copy()
                del provider_details[f]
                with self.assertRaises(HTTPException):
                    steamopenid.authenticate(dict(provider='steamopenid', provider_details=provider_details))


    def test_fails_with_invalid_oauth_response(self):
        with mock.patch('driftbase.auth.steamopenid.get_provider_config') as config:
            config.return_value = self.valid_config
            with mock.patch('driftbase.auth.steamopenid.get_steam_openid_identity') as get_steam_openid_identity:
                # missing the 'id' key
                get_steam_openid_identity.return_value = {}
                with self.assertRaises(KeyError):
                    steamopenid.authenticate(dict(provider='steamopenid', provider_details=self.valid_provider_details))
                
    