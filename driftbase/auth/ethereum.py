import datetime
import http.client as http_client
import json
import logging
from hashlib import pbkdf2_hmac
from json import JSONDecodeError

import eth_keys.exceptions
import eth_utils.exceptions
import marshmallow as ma
import siwe
from drift.blueprint import abort
from eth_account import Account
from eth_account.messages import encode_defunct, defunct_hash_message
from web3 import Web3

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate, AuthenticationException, ServiceUnavailableException, \
    abort_unauthorized, InvalidRequestException, UnauthorizedException

log = logging.getLogger(__name__)

DEFAULT_TIMESTAMP_LEEWAY = 60

CONTRACT_SIGNER_ERC1271 = 'ERC1271'

def utcnow():
    return datetime.datetime.utcnow()


class EthereumProviderAuthDetailsSchema(ma.Schema):
    signer = ma.fields.String(required=True, allow_none=False)
    message = ma.fields.String(required=True, allow_none=False)
    signature = ma.fields.String(required=True, allow_none=False)
    contract_signer_type = ma.fields.String(required=False, allow_none=False)
    chain_id = ma.fields.Int(required=False, allow_none=False)


def authenticate(auth_info):
    assert auth_info['provider'] == 'ethereum'

    try:
        parameters = _load_provider_details(auth_info['provider_details'])
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except KeyError as e:
        abort(http_client.BAD_REQUEST, message="Missing provider_details")
    
    signer = parameters['signer']
    message = parameters['message']
    signature = parameters['signature']
    contract_signer_type = parameters['contract_signer_type']
    try:
        if contract_signer_type:
            identity_id = _validate_contract_message(**parameters)
        else:
            identity_id = _validate_ethereum_message(signer=signer, message=message, signature=signature)         
    except ServiceUnavailableException as e:
        abort(http_client.SERVICE_UNAVAILABLE, message=e.msg)
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except AuthenticationException as e:
        abort_unauthorized(e.msg)

    automatic_account_creation = auth_info.get('automatic_account_creation', True)
    # We no longer hash the user ID, so we pass the old "username" as a fallback to be upgraded
    username = f"ethereum:{identity_id}"
    # FIXME: The static salt should perhaps be configured per tenant
    fallback_username = "ethereum:" + pbkdf2_hmac('sha256', identity_id.encode('utf-8'), b'static_salt',
                                                  iterations=1).hex()
    return base_authenticate(username, "", automatic_account_creation, fallback_username=fallback_username)


def _load_provider_details(provider_details):
    try:
        parameters = EthereumProviderAuthDetailsSchema().load(provider_details)
        contract_signer_type = parameters.get('contract_signer_type', None)
        chain_id = parameters.get('chain_id', None)
        if bool(contract_signer_type) != bool(chain_id):
            raise InvalidRequestException("Either contract_signer_type or chain_id must be provided")
        parameters['contract_signer_type'] = contract_signer_type
        parameters['chain_id'] = chain_id
        return parameters
    except ma.exceptions.ValidationError as e:
        raise InvalidRequestException(f"{e}") from None


def _validate_erc1271_signature(chain_id, signer, message, signature, ethereum_config):
    '''
    See https://eips.ethereum.org/EIPS/eip-1271
    '''
    rpcs = ethereum_config.get('rpcs', {})
    abi = """
    [
        {
            "constant": true,
            "inputs": [
                {
                    "name": "",
                    "type": "bytes32"
                },
                {
                    "name": "",
                    "type": "bytes"
                }
            ],
            "name": "isValidSignature",
            "outputs": [
                {
                    "name": "",
                    "type": "bytes4"
                }
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]
    """
    chain_id_str = str(chain_id)
    if chain_id_str not in rpcs:
        raise InvalidRequestException(f"Unsupported chain_id: {chain_id}")
    try:
        rpc = rpcs[chain_id_str]
        web3 = Web3(Web3.HTTPProvider(rpc))
        contract = web3.eth.contract(address=signer, abi=abi)
        message_hash = defunct_hash_message(text=message)
        result = contract.functions.isValidSignature(message_hash, Web3.to_bytes(hexstr=signature)).call()
    except Exception as e:
        log.error(f"Error validating immutable contract signature: {e}", 
                    extra=dict(chain_id=chain_id, signer=signer, user_message=message, signature=signature))
        raise InvalidRequestException("Signature validation failed") from None
    result = '0x' + result.hex()
    ERC_1271_MAGIC_VALUE = '0x1626ba7e'
    if result != ERC_1271_MAGIC_VALUE:
        log.error(f"Unexpected result when validating contract signature: {result}", 
                    extra=dict(expected=ERC_1271_MAGIC_VALUE, chain_id=chain_id, signer=signer, user_message=message, signature=signature))
        raise InvalidRequestException("Signature validation failed")


def _validate_contract_message(chain_id, contract_signer_type, signer, message, signature):
    ethereum_config = get_provider_config('ethereum')
    if ethereum_config is None:
        raise ServiceUnavailableException("Ethereum authentication not configured for current tenant")

    timestamp_leeway = ethereum_config.get('timestamp_leeway', DEFAULT_TIMESTAMP_LEEWAY)

    try:
        # validate the timestamp before calling the contract
        message_json = json.loads(message)
        _validate_message_timestamp(message_json, timestamp_leeway)

        if contract_signer_type == CONTRACT_SIGNER_ERC1271:
            _validate_erc1271_signature(chain_id=chain_id, signer=signer, message=message, signature=signature, ethereum_config=ethereum_config)
        else:
            raise InvalidRequestException(f"Unsupported contract signer type: {contract_signer_type}")
        log.info("Ethereum contract login succeeded", extra=dict(signer=signer, payload=message_json, chain_id=chain_id))
        return signer.lower()
    except JSONDecodeError:
        raise InvalidRequestException("Message is not valid JSON") from None    


def _validate_message_timestamp(message_json, timestamp_leeway):
    try:
        timestamp = datetime.datetime.fromisoformat(message_json['timestamp'][:-1])
        if utcnow() - timestamp > datetime.timedelta(seconds=timestamp_leeway):
            log.info("Login failed: Timestamp out of bounds",
                        extra=dict(ticket_time=timestamp, current_time=utcnow(), time_diff=utcnow() - timestamp,
                                leeway=timestamp_leeway))
            raise UnauthorizedException("Timestamp out of bounds")
        if utcnow() + datetime.timedelta(seconds=timestamp_leeway) < timestamp:
            log.info("Login failed: Timestamp is in the future",
                        extra=dict(ticket_time=timestamp, current_time=utcnow(), time_diff=utcnow() - timestamp,
                                leeway=timestamp_leeway))
            raise UnauthorizedException("Timestamp is in the future")
    except KeyError:
        raise UnauthorizedException("Missing timestamp")


def _validate_ethereum_message(signer, message, signature):
    ethereum_config = get_provider_config('ethereum')
    if ethereum_config is None:
        raise ServiceUnavailableException("Ethereum authentication not configured for current tenant")

    timestamp_leeway = ethereum_config.get('timestamp_leeway', DEFAULT_TIMESTAMP_LEEWAY)

    return _run_ethereum_message_validation(signer, message, signature, timestamp_leeway=timestamp_leeway)


def _run_ethereum_message_validation(signer, message, signature, timestamp_leeway=DEFAULT_TIMESTAMP_LEEWAY):
    """
    Validate an Ethereum message signature and return the signer address in lowercase if valid.
    """
    try:
        message_json = json.loads(message)
        try:
            recovered = Account().recover_message(encode_defunct(text=message), signature=signature).lower()
        except eth_utils.exceptions.ValidationError:
            raise InvalidRequestException("Signature validation failed") from None
        except ValueError:
            raise InvalidRequestException("Signature contains invalid characters") from None
        except eth_keys.exceptions.BadSignature:
            raise InvalidRequestException("Bad signature") from None
        _validate_message_timestamp(message_json, timestamp_leeway)        
        if recovered != signer.lower():
            raise UnauthorizedException("Signer does not match passed in address")

        log.info("Ethereum login succeeded", extra=dict(signer=recovered, payload=message_json))

    except JSONDecodeError:
        # Message is not JSON, it's probably EIP-4361
        try:
            siwe_message: siwe.SiweMessage = siwe.SiweMessage.from_message(message=message)
            siwe_message.verify(signature, timestamp=utcnow())
            recovered = signer.lower()
        except ValueError:
            raise UnauthorizedException("Invalid message format")
        except siwe.ExpiredMessage:
            raise UnauthorizedException("Message expired")
        except siwe.MalformedSession:
            raise UnauthorizedException("Session is malformed")
        except siwe.InvalidSignature:
            raise UnauthorizedException("Bad signature")

    return recovered
