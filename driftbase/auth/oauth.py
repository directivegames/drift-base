from drift.blueprint import abort
from werkzeug.exceptions import Unauthorized
import marshmallow as ma

import requests
import http.client as http_client

import logging

log = logging.getLogger(__name__)


class DefaultOAuthDetailsSchema(ma.Schema):
    token = ma.fields.String(required=True, allow_none=False)


class BaseOAuthValidator:
    def __init__(self, name, details_schema=DefaultOAuthDetailsSchema):
        self.name = name
        self.details_schema = details_schema        
    
    def _get_identity(self, provider_details: dict) -> requests.Response | dict:
        '''call the identity endpoint with the oauth access token and return the response object'''
        raise NotImplementedError()
    

    def _abort_unauthorized(self, error):
        description = f'{self.name} code validation failed. {error}'
        raise Unauthorized(description=description)
    

    def get_oauth_identity(self, provider_details) -> dict:
        '''get the identity from the oauth code and return the identity object as dict'''
        try:
            self.details_schema().load(provider_details)
        except ma.exceptions.ValidationError as e:
            abort(http_client.BAD_REQUEST, description=f'Invalid provider details: "{e}"')
        
        # get identity from the access token
        try:
            r = self._get_identity(provider_details)
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
    
