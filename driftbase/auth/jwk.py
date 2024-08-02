from json import JSONDecodeError
from urllib.error import URLError

import jwt

from driftbase.auth.authenticate import ServiceUnavailableException, UnauthorizedException


def _get_key_from_token(token, cognito_public_keys_url):
    try:
        jwk_client = _get_jwk_client(cognito_public_keys_url)
        jwk = jwk_client.get_signing_key_from_jwt(token)
    except URLError as e:
        raise ServiceUnavailableException("Failed to fetch public keys for token validation") from e
    except (JSONDecodeError, jwt.PyJWKClientError) as e:
        raise ServiceUnavailableException("Failed to read public keys for token validation") from None

    if jwk is None:
        raise UnauthorizedException("Failed to find a matching public key for token validation")
    return jwk.key


_jwk_clients = {}


def _get_jwk_client(public_keys_url):
    global _jwk_clients
    client = _jwk_clients.get(public_keys_url)
    if client is None:
        client = jwt.PyJWKClient(public_keys_url, cache_keys=True, cache_jwk_set=True)
        _jwk_clients[public_keys_url] = client
    return client
