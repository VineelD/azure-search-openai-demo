import logging

from azure.core.exceptions import HttpResponseError
from openai import APIError
from quart import jsonify

ERROR_MESSAGE = """The app encountered an error processing your request.
If you are an administrator of the app, check the application logs for a full traceback.
Error type: {error_type}
"""
ERROR_MESSAGE_FILTER = """Your message contains content that was flagged by the OpenAI content filter."""

ERROR_MESSAGE_LENGTH = """Your message exceeded the context length limit for this OpenAI model. Please shorten your message or change your settings to retrieve fewer search results."""

ERROR_MESSAGE_AZURE = """Azure service error: {message}
If indexing is in progress, try again in a minute. Error type: {error_type}"""


def error_dict(error: Exception) -> dict:
    if isinstance(error, APIError) and error.code == "content_filter":
        return {"error": ERROR_MESSAGE_FILTER}
    if isinstance(error, APIError) and error.code == "context_length_exceeded":
        return {"error": ERROR_MESSAGE_LENGTH}
    if isinstance(error, HttpResponseError):
        msg = getattr(error, "message", None) or str(error)
        status = getattr(error.response, "status_code", None) if getattr(error, "response", None) else None
        if status:
            msg = f"[HTTP {status}] {msg}"
        return {"error": ERROR_MESSAGE_AZURE.format(message=msg, error_type=type(error).__name__)}
    return {"error": ERROR_MESSAGE.format(error_type=type(error))}


def error_response(error: Exception, route: str, status_code: int = 500):
    logging.exception("Exception in %s: %s", route, error)
    if isinstance(error, APIError) and error.code == "content_filter":
        status_code = 400
    return jsonify(error_dict(error)), status_code
