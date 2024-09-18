"""
FIXME: This file has huge overlap with drift-season/utils/exceptions, and probably other services. What
tools do we have to share code between these services? Should this be moved into Drift?
"""

import http.client as http_client

class DriftBaseException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message
    def error_code(self):
        return http_client.INTERNAL_SERVER_ERROR

class InvalidRequestException(DriftBaseException):
    def error_code(self):
        return http_client.BAD_REQUEST

class NotFoundException(DriftBaseException):
    def error_code(self):
        return http_client.NOT_FOUND

class UnauthorizedException(DriftBaseException):
    def error_code(self):
        return http_client.UNAUTHORIZED

class ConflictException(DriftBaseException):
    def error_code(self):
        return http_client.CONFLICT

class ForbiddenException(DriftBaseException):
    def error_code(self):
        return http_client.FORBIDDEN

class TryLaterException(DriftBaseException):
    def error_code(self):
        return http_client.SERVICE_UNAVAILABLE