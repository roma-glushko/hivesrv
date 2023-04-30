import logging
from typing import cast

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from hive.config import Config
from hive.servers.base import run
from hive.servers.tcp.server import TCPServer

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s - %(name)s:%(lineno)d - %(message)s',
    datefmt='%H:%M:%S'
)


def homepage(request):
    return PlainTextResponse('Hello, world!')


def user_me(request):
    username = "John Doe"
    return PlainTextResponse('Hello, %s!' % username)


def user(request):
    username = request.path_params['username']
    return PlainTextResponse('Hello, %s!' % username)


async def websocket_endpoint(websocket):
    await websocket.accept()
    await websocket.send_text('Hello, websocket!')
    await websocket.close()


def startup():
    print('Ready to go')


routes = [
    Route('/', homepage),
    Route('/users/me/', user_me),
    Route('/users/{username}/', user),
    # WebSocketRoute('/ws', websocket_endpoint),
]

app = Starlette(debug=True, routes=routes, on_startup=[startup])


run(TCPServer(config=Config(app=app)))
