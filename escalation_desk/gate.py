"""The approval gate: what an agent may do on its own, and what waits for a person.

The rule is simple on purpose. Reversible, private, observable work runs.
Anything that moves money, deletes data, makes a new promise, or reaches a
stranger stops and waits for a human. Unknown actions are treated as
consequential: the gate fails closed.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

AUTO = "auto"
HUMAN = "human"

DEFAULT_POLICY: Dict[str, str] = {
    # runs on its own
    "reply_in_thread": AUTO,
    "read_state": AUTO,
    "edit_agent_instructions": AUTO,   # with a backup; see handlers
    "add_note": AUTO,
    # waits for a person
    "send_payment": HUMAN,
    "refund": HUMAN,
    "new_price": HUMAN,
    "delete_data": HUMAN,
    "contact_stranger": HUMAN,
    "deploy_production": HUMAN,
}


@dataclass
class Action:
    kind: str
    detail: str = ""


@dataclass
class Verdict:
    allowed: List[Action] = field(default_factory=list)
    held: List[Action] = field(default_factory=list)

    @property
    def needs_human(self) -> bool:
        return bool(self.held)


def review(actions: Iterable[Action], policy: Dict[str, str] = DEFAULT_POLICY) -> Verdict:
    v = Verdict()
    for a in actions:
        (v.allowed if policy.get(a.kind) == AUTO else v.held).append(a)
    return v
