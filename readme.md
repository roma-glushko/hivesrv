# Hive

This is a PoC of a Python3 ASGI server that is designed to serve cloud native applications that run in Kubernetes. 

Hive focuses on what Kubernetes supports and provides for application developers and 
tries to enable those capabilities without headache.

## Architecture

Hive respects [ASGI's](https://asgi.readthedocs.io/en/latest/introduction.html#introduction) approach to building 
network-based applications and consists of similar two parts:

- Protocol Server (Low-level network server piece that supports Kubernetes capabilities)
- App Framework Integrations (Starlette and FastAPI are the main targets)

## Features To Support

- TCP/UDP servers
- HTTP 1.1 protocol
- multi-port support
- graceful shutdowns
- resilient connection handling not based on asyncio's loop.create_server()

## Credits

This project is staying on the shoulders of giants:

- https://pgjones.gitlab.io/hypercorn/
- https://github.com/encode/uvicorn

