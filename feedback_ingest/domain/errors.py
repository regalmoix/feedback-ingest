class PermanentError(Exception):
    pass


class TransientError(Exception):
    pass


class NotFoundError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


class ConflictError(Exception):
    pass


def check_limit(limit: int) -> int:
    if limit < 1:
        msg = "limit must be >= 1"
        raise ValueError(msg)
    return limit
