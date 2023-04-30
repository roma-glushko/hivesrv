import asyncio
import weakref

from hive.loops import setup_uviloop


class Server:
    async def startup(self) -> None:
        ...

    async def serve(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...


def run(server: Server) -> None:
    setup_uviloop()

    return asyncio.run(server.serve())
