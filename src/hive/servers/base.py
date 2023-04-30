import asyncio
from typing import Optional

import uvloop


class Server:
    async def startup(self) -> None:
        ...

    async def serve(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...

    def on_shutdown_signal(self, graceful_shutdown: bool = True, signal: Optional[int] = None):
        ...


def run(server: Server) -> None:
    uvloop.install()

    return asyncio.run(server.serve())
