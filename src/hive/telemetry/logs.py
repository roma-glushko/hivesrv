from enum import Enum


class Logs(str, Enum):
    HIVE_SERVER_STARTED = "HIVE_SERVER_STARTED"
    HIVE_SERVER_SIGNAL_RECEIVED = "HIVE_SERVER_SIGNAL_RECEIVED"
    HIVE_SERVER_SHUTDOWN_GRACEFUL = "HIVE_SERVER_SHUTDOWN_GRACEFUL"
    HIVE_SERVER_SHUTDOWN_WAIT_FOR_NO_REQUESTS = "HIVE_SERVER_SHUTDOWN_WAIT_FOR_NO_REQUESTS"
    HIVE_SERVER_SHUTDOWN_FORCEFUL = "HIVE_SERVER_SHUTDOWN_FORCEFUL"
    HIVE_SERVER_SHUTDOWN_COMPLETED = "HIVE_SERVER_SHUTDOWN_COMPLETED"
