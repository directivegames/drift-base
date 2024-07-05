from drift.blueprint import abort
from driftbase.auth import get_provider_config
from werkzeug.exceptions import Unauthorized

import requests
import http.client as http_client

import logging

log = logging.getLogger(__name__)

class BaseOAuthValidator:
    def __init__(self, name):
        self.name = name
        self.config = get_provider_config(self.name)            
    
    def _get_details_fields(self) -> list[str]:
        '''return required fields in provider_details'''
        return ['code', 'redirect_uri']
    
    
    def _call_oauth(self, client_id: str, client_secret: str, provider_details: dict) -> requests.Response:
        '''call the oauth endpoint and return the response object'''
        raise NotImplementedError()
    

    def _get_identity(self, access_token: str) -> requests.Response:
        '''call the identity endpoint with the oauth access token and return the response object'''
        raise NotImplementedError()
    

    def get_oauth_identity(self, provider_details) -> dict:
        '''get the identity from the oauth code and return the identity object as dict'''
        if not self.config:
            abort(http_client.SERVICE_UNAVAILABLE, description=f'{self.name} authentication not configured for current tenant')
        
        client_id = self.config.get('client_id')
        client_secret = self.config.get('client_secret')
        if not client_id or not client_secret:
            log.error(f'{self.name} OAuth code cannot be validated, client_id or client_secret not configured')
            abort(http_client.SERVICE_UNAVAILABLE, description=f'{self.name} authentication not configured correctly')

        fields = self._get_details_fields()
        for f in fields:
            if f not in provider_details:
                abort(http_client.BAD_REQUEST, description=f'Invalid provider details, missing field "{f}"')

        def abort_unauthorized(error):
            description = f'{self.name} code validation failed for client {client_id}. {error}'
            raise Unauthorized(description=description)
        
        # call oauth to get the access token
        try:
            r = self._call_oauth(client_id, client_secret, provider_details)
        except requests.exceptions.RequestException as e:
            abort_unauthorized(str(e))
        if r.status_code != 200:
            abort_unauthorized(f'{self.name} oauth API status code: {r.status_code}')

        tokens = r.json()
        access_token = tokens['access_token']

        # get identity from the access token
        try:
            r = self._get_identity(access_token)            
        except requests.exceptions.RequestException as e:
            abort_unauthorized(str(e))
        if r.status_code != 200:
            abort_unauthorized(f'{self.name} identity API status code: {r.status_code}')

        identity = r.json()
        log.info(f'{self.name} identity authenticated: {identity}')
        
        return identity
    
