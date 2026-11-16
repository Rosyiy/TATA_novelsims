"""Shared error type carrying a machine readable code and an HTTP status."""


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        Exception.__init__(self, message or code)
        self.status = status
        self.code = code
        self.message = message or code
