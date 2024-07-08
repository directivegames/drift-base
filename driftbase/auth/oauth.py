from drift.blueprint import abort
from driftbase.auth import get_provider_config
from werkzeug.exceptions import Unauthorized

import requests
import http.client as http_client

import logging

log = logging.getLogger(__name__)

class BaseOAuthValidator:
    def __init__(self, name, config_fields=['client_id', 'client_secret'], details_fields=['code', 'redirect_uri']):
        self.name = name
        self.config_fields = config_fields
        self.details_fields = details_fields
        self.config = get_provider_config(self.name)
    
    def _call_oauth(self, provider_details: dict) -> requests.Response:
        '''call the oauth endpoint and return the response object'''
        raise NotImplementedError()
    

    def _get_identity(self, response: requests.Response, provider_details: dict) -> requests.Response | dict:
        '''call the identity endpoint with the oauth access token and return the response object'''
        raise NotImplementedError()
    

    def _abort_unauthorized(self, error):
        description = f'{self.name} code validation failed. {error}'
        raise Unauthorized(description=description)
    

    def get_oauth_identity(self, provider_details) -> dict:
        '''get the identity from the oauth code and return the identity object as dict'''
        if not self.config:
            abort(http_client.SERVICE_UNAVAILABLE, description=f'{self.name} authentication not configured for current tenant')

        for f in self.config_fields:
            if f not in self.config:
                log.error(f'{self.name} OAuth code cannot be validated, missing field "{f}" in config')
                abort(http_client.SERVICE_UNAVAILABLE, description=f'{self.name} authentication not configured correctly')
        
        for f in self.details_fields:
            if f not in provider_details:
                abort(http_client.BAD_REQUEST, description=f'Invalid provider details, missing field "{f}"')        
        
        # call oauth to get the access token
        try:
            r = self._call_oauth(provider_details)
        except requests.exceptions.RequestException as e:
            self._abort_unauthorized(str(e))
        if r.status_code != 200:
            self._abort_unauthorized(f'{self.name} oauth API status code: {r.status_code}')        

        # get identity from the access token
        try:
            r = self._get_identity(r, provider_details)
        except requests.exceptions.RequestException as e:
            self._abort_unauthorized(str(e))

        if type(r) == requests.Response:
            if r.status_code != 200:
                self._abort_unauthorized(f'{self.name} identity API status code: {r.status_code}')
            identity = r.json()
        else:
            identity = r
        log.info(f'{self.name} identity authenticated: {identity}')
        
        return identity
    
