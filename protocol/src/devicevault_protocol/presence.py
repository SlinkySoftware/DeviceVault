"""Shared protocol constants for worker registration and liveliness messages."""

WORKER_EVENTS_EXCHANGE = 'devicevault.worker.events'
WORKER_EVENTS_ROUTING_KEY = 'worker.event'
WORKER_EVENTS_QUEUE = 'devicevault.orchestrator.worker_events'

WORKER_CONTROL_EXCHANGE = 'devicevault.worker.control'

EVENT_REGISTER = 'register'
EVENT_HEARTBEAT = 'heartbeat'
EVENT_PONG = 'pong'
EVENT_PING = 'ping'
