import asyncio
import threading
import time
import requests
from requests import Response
from enum import Enum

from core.config import get
from core.constants import STATUS_SUCCESS

class HttpMethod(Enum):
    GET = 'GET'
    POST = 'POST'
    PUT = 'PUT'
    DELETE = 'DELETE'
    PATCH = 'PATCH'

def is_response_successful(response: requests.Response) -> bool:
    """
    Check if the HTTP response was successful.

    Args:
        response (requests.Response): The HTTP response object.

    Returns:
        bool: True if the response status code is 200, False otherwise.
    """
    return response.status_code == STATUS_SUCCESS

# Crafty answers slowly while it is busy (e.g. zipping a backup), so give it some time before giving up
DEFAULT_TIMEOUT = 15
# while Crafty is unreachable, the same error is only printed this often (seconds)
ERROR_REPEAT = 600


class _Reachability:
    """
    Prints connection errors once when Crafty becomes unreachable and once when it is back,
    instead of one line for every request of every loop.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.failing_since = None
        self.last_print = 0.0
        self.failures = 0

    def failed(self, error: Exception) -> None:
        with self.lock:
            now = time.time()
            self.failures += 1
            if self.failing_since is None:
                self.failing_since = now
            elif now - self.last_print < ERROR_REPEAT:
                return
            self.last_print = now
            print(f"Request failed: {error}" + (f" ({self.failures} failed requests so far, "
                                                 f"repeats are not shown)" if self.failures > 1 else ""))

    def succeeded(self) -> None:
        if self.failing_since is None:
            return
        with self.lock:
            if self.failing_since is None:
                return
            print(f"Crafty reachable again after {time.time() - self.failing_since:.0f}s "
                  f"({self.failures} failed requests)")
            self.failing_since = None
            self.failures = 0

    @property
    def failing(self) -> bool:
        return self.failing_since is not None


reachability = _Reachability()


def send_request(path: str, verify: bool = False, timeout: int = DEFAULT_TIMEOUT, data: dict = None, method: HttpMethod = HttpMethod.GET) -> Response:
    """
    Send an HTTP request with the specified method to the given path and return the response.

    Args:
        method (HttpMethod, optional): The HTTP method to use. Defaults to HttpMethod.GET.
        path (str): The URL path to send the request to.
        verify (bool, optional): Whether to verify the server's TLS certificate. Defaults to False.
        timeout (int, optional): The timeout for the request in seconds. Defaults to DEFAULT_TIMEOUT.
        data (dict, optional): The data to send in the request body (for POST, PUT, etc.). Defaults to None.

    Returns:
        requests.Response: The HTTP response object.
    """
    url = get('crafty.url').rstrip('/') + path
    headers = {'Authorization': 'Bearer ' + get('crafty.token')}
    try:
        response = requests.request(method.value, url, headers=headers, verify=verify, timeout=timeout, json=data)
    except requests.RequestException as e:
        reachability.failed(e)
        return Response()
    reachability.succeeded()
    return response

async def get_json_response(path: str, error_message: str = "Error while response", method: HttpMethod = HttpMethod.GET, data: dict = None) -> dict:
    """
    Send an HTTP request with the specified method to the given path and return the response as JSON.

    The blocking request runs in a worker thread so it does not stall the Discord event loop.

    Args:
        method (HttpMethod, optional): The HTTP method to use. Defaults to HttpMethod.GET.
        path (str): The URL path to send the request to.
        error_message (str, optional): The error message to print if the response is not successful. Defaults to "Error while response".
        data (dict, optional): The data to send in the request body (for POST, PUT, etc.). Defaults to None.

    Returns:
        dict: The JSON response as a dictionary. Returns an empty dictionary if the response is not successful.
    """
    response = await asyncio.to_thread(send_request, path, method=method, data=data)
    if not is_response_successful(response):
        # Crafty did not answer at all: send_request already reported that
        if response.status_code is not None:
            print(f"{error_message} ({response.status_code})")
        return {}
    try:
        return response.json()
    except ValueError:
        print(f"{error_message}: invalid JSON")
        return {}


def upload_file(path: str, content: bytes, headers: dict, timeout: int = 15) -> Response:
    """
    Send a file as the raw request body to the given path, with extra headers. Returns the response.
    """
    url = get('crafty.url').rstrip('/') + path
    headers = {'Authorization': 'Bearer ' + get('crafty.token'), 'Content-Type': 'application/octet-stream', **headers}
    try:
        response = requests.post(url, headers=headers, data=content, verify=False, timeout=timeout)
    except requests.RequestException as e:
        reachability.failed(e)
        return Response()
    reachability.succeeded()
    return response
