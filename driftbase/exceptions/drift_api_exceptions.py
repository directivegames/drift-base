class DriftApiException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message

class InvalidRequestException(DriftApiException):
    pass

class NotFoundException(DriftApiException):
    pass

class UnauthorizedException(DriftApiException):
    pass

class ConflictException(DriftApiException):
    pass

class ForbiddenException(DriftApiException):
    pass