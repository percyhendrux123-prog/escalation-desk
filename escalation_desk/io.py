"""Where messages come from and where replies go.

The real deployment reads iMessage on a Mac and replies through it. Here both
sides are plain JSONL files so the whole loop runs anywhere. Swap in your own
classes with the same two methods.
"""
import json
import os
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class Message:
    id: str        # stable, increasing id from the source (e.g. a chat.db ROWID)
    thread: str
    sender: str
    text: str


class JsonlSource:
    """One JSON object per line: {"id", "thread", "sender", "text"}."""

    name = "jsonl"

    def __init__(self, path: str):
        self.path = path

    def since(self, last_id: Optional[str]) -> Iterator[Message]:
        if not os.path.exists(self.path):
            return
        with open(self.path) as f:
            for line in f:
                if not line.strip():
                    continue
                m = Message(**json.loads(line))
                if last_id is None or int(m.id) > int(last_id):
                    yield m


class JsonlChannel:
    """Appends outbound messages to a file. Replace with your real channel."""

    def __init__(self, path: str):
        self.path = path

    def send(self, thread: str, text: str) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"thread": thread, "text": text}) + "\n")
