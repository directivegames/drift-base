import requests

from drift.systesthelper import DriftBaseTestCase


class LocalAuthTests(DriftBaseTestCase):
    def test_legacy_user_pass_without_provider(self):
        data = {
            'username': 'abc',
            'password': '123',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_legacy_user_pass_with_provider(self):
        data = {
            'username': 'abc',
            'password': '123',
            'provider': 'user+pass',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_user_pass_with_provider_details(self):
        data = {
            'provider': 'user+pass',
            'provider_details': {
                'username': 'abc',
                'password': '123',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_user_pass_with_missing_data(self):
        data = {
            'username': 'abc',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'password': '123',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'provider': 'user+pass',
            'provider_details': {
                'username': 'abc',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'provider': 'user+pass',
            'provider_details': {
                'password': '123',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)

class UuidAuthTests(DriftBaseTestCase):
    def test_legacy_uuid_without_provider(self):
        data = {
            'username': 'uuid:abc',
            'password': '123',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_legacy_uuid_with_provider(self):
        data = {
            'username': 'abc',
            'password': '123',
            'provider': 'uuid',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_uuid_with_provider_details(self):
        data = {
            'provider': 'uuid',
            'provider_details': {
                'key': 'abc',
                'secret': '123',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.OK)

    def test_uuid_with_missing_data(self):
        data = {
            'username': 'abc',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'password': '123',
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'provider': 'uuid',
            'provider_details': {
                'key': 'abc',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)
        data = {
            'provider': 'uuid',
            'provider_details': {
                'secret': '123',
            }
        }
        self.post('/auth', data=data, expected_status_code=requests.codes.BAD_REQUEST)

