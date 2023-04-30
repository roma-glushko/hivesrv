import signal


GRACEFUL_SHUTDOWN_SIGNALS = {
    signal.SIGTERM  # Kubernetes sends it when pod termination started
}

FORCE_SHUTDOWN_SIGNALS = {
    signal.SIGINT,   # Sent by Ctrl+C.
    signal.SIGKILL,  # Kubernetes sends it after the graceful termination timeout + 2s
}
