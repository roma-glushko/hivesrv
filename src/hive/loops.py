import asyncio
import uvloop


def setup_uviloop() -> None:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
