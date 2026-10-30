"""escalation-desk: get an agent's escalations to a person-safe resolution."""
from .desk import Desk, Resolution, HOLDING_LINE
from .gate import Action, review
from .io import JsonlChannel, JsonlSource, Message
from .store import Store

__all__ = ["Desk", "Resolution", "HOLDING_LINE", "Action", "review",
           "JsonlChannel", "JsonlSource", "Message", "Store"]
__version__ = "0.1.0"
