from typing import Union, Callable, TYPE_CHECKING

from h11._connection import DEFAULT_MAX_INCOMPLETE_EVENT_SIZE

if TYPE_CHECKING:
    from asgiref.typing import ASGIApplication


class Config:

    def __init__(
        self,
        app: Union["ASGIApplication", Callable, str],
        host: str = "127.0.0.1",
        port: int = 8000,
        backlog: int = 2048,
        h11_max_incomplete_event_size: int = DEFAULT_MAX_INCOMPLETE_EVENT_SIZE,
        timeout_keep_alive_sec: int = 5,
        asgi_version: str = "3.0",
        root_path: str = "",
    ) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.backlog = backlog
        self.h11_max_incomplete_event_size = h11_max_incomplete_event_size
        self.timeout_keep_alive_sec = timeout_keep_alive_sec
        self.asgi_version = asgi_version
        self.root_path = root_path
