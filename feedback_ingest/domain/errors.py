class TransformError(Exception):
    pass


class TransientError(Exception):
    pass


class NotFoundError(Exception):
    pass


def check_limit(limit: int) -> int:
    if limit < 1:
        msg = "limit must be >= 1"
        raise ValueError(msg)
    return limit
