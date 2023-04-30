import asyncio
import weakref
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hive.servers.tcp.http.http11 import HTTP11Protocol


class TCPServerState:
    def __init__(self) -> None:
        self.total_requests = 0
        self.last_request_at = 0
        self.connections: set["HTTP11Protocol"] = set()
        self.tasks: weakref.WeakSet[asyncio.Task] = weakref.WeakSet()
