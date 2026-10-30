"""The two loops: a watcher that turns escalations into tickets, and a
dispatcher that works tickets through a handler and the approval gate.

Watcher, per new message:
  1. Is it addressed to the operator agent? If not, ignore it.
  2. Send one holding line, so the person knows it landed.
  3. Open one ticket. A message can never open two.

Dispatcher, per ticket:
  1. Claim it with a lease. If the worker dies, the lease runs out and
     another worker picks it up.
  2. Run the handler. It returns a reply, evidence, and the actions it wants.
  3. The gate splits actions into allowed and held.
  4. If anything is held, the ticket goes to a human and no reply is sent
     that pretends the work is done.
  5. Otherwise send the reply (at most once) and close the ticket with
     its evidence.
"""
import re
import socket
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .gate import Action, review
from .io import Message
from .store import Store

DEFAULT_TRIGGER = re.compile(r"^\s*(axiom|operator)\s*[,:]", re.IGNORECASE)
HOLDING_LINE = "Got it. This is with the operator now and you'll hear back shortly."


@dataclass
class Resolution:
    reply: str
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    actions: List[Action] = field(default_factory=list)


Handler = Callable[[Any], Resolution]


class Desk:
    def __init__(self, store: Store, source, channel, trigger=DEFAULT_TRIGGER,
                 holding_line: str = HOLDING_LINE, ticket_prefix: str = "E"):
        self.store = store
        self.source = source
        self.channel = channel
        self.trigger = trigger
        self.holding_line = holding_line
        self.prefix = ticket_prefix

    # sending --------------------------------------------------------------
    def send_once(self, idem_key: str, thread: str, text: str) -> bool:
        """Send unless this exact send already happened. Never double-texts."""
        if not self.store.record_send(idem_key, thread, text):
            return False
        self.channel.send(thread, text)
        return True

    # watcher --------------------------------------------------------------
    def is_escalation(self, m: Message) -> bool:
        return bool(self.trigger.search(m.text))

    def watch_once(self) -> List[int]:
        opened: List[int] = []
        last = self.store.get_cursor(self.source.name)
        for m in self.source.since(last):
            if self.is_escalation(m):
                tid = self.store.open_ticket(m.id, m.thread, m.text, self.prefix)
                if tid is not None:
                    opened.append(tid)
                # Called on every pass, not just the first: if we crashed between
                # opening the ticket and sending, this still sends exactly once.
                if self.send_once(f"hold:{m.id}", m.thread, self.holding_line):
                    self.store.event("holding_sent", tid, source_msg_id=m.id)
            # advance only after the message is fully handled
            self.store.set_cursor(self.source.name, m.id)
        return opened

    # dispatcher -----------------------------------------------------------
    def work_once(self, handler: Handler, worker: Optional[str] = None,
                  lease_s: float = 900, max_attempts: int = 3) -> Optional[int]:
        worker = worker or f"{socket.gethostname()}"
        t = self.store.claim(worker, lease_s)
        if t is None:
            return None
        tid = t["id"]
        if t["attempts"] > max_attempts:
            # Stop retrying something that keeps failing; a person looks at it.
            self.store.finish(tid, "needs_human",
                              f"Failed {max_attempts} times; handing to a person.", {})
            return tid
        try:
            res = handler(t)
        except Exception as e:  # leave it claimed; the lease expiry retries it
            self.store.event("handler_error", tid, error=repr(e)[:200])
            return tid

        verdict = review(res.actions)
        evidence = dict(res.evidence)
        evidence["allowed"] = [a.kind for a in verdict.allowed]
        evidence["held"] = [a.kind for a in verdict.held]

        if verdict.needs_human:
            self.store.finish(tid, "needs_human",
                              "Held for a person: " + ", ".join(a.kind for a in verdict.held),
                              evidence)
            return tid

        sent = self.send_once(f"reply:{t['source_msg_id']}", t["thread"], res.reply)
        evidence["reply_sent"] = sent
        self.store.finish(tid, "done", res.summary, evidence)
        return tid
