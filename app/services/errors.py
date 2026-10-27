class DomainError(Exception):
    def __init__(self, message, status=422, code='validation', fields=None):
        super().__init__(message)
        self.message, self.status, self.code, self.fields = message, status, code, fields or {}


def require(condition, message, status=422, code='validation'):
    if not condition:
        raise DomainError(message, status, code)
