from __future__ import annotations


def detach_exception(error: BaseException) -> str:
    """Drop traceback-held model graphs before the request's CUDA cleanup runs."""
    message = str(error)
    error.__traceback__ = None
    error.__cause__ = None
    error.__context__ = None
    return message
