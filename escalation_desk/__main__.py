"""Run the demo: python -m escalation_desk demo

Replays a real kind of night. A client's own agent is stuck in the middle of
a job and asks the operator for help. The watcher catches it, the person
gets a holding line, a worker diagnoses the problem, and the reply goes out
once. A second escalation asks for a refund; the gate holds it for a human.
"""
import json
import os
import sys
import tempfile

from . import Action, Desk, JsonlChannel, JsonlSource, Resolution, Store

INBOX = [
    {"id": "100", "thread": "client-1", "sender": "client", "text": "Bad??"},
    {"id": "101", "thread": "client-1", "sender": "client-agent",
     "text": "Axiom, the desktop chat app shows no usable window during intake. "
             "The launch post is held unsent because I can't verify the destination. "
             "Can you check without interrupting the client's video call?"},
    {"id": "102", "thread": "client-2", "sender": "client",
     "text": "Axiom: please refund last month, I was traveling."},
]


def handler(t) -> Resolution:
    body = t["body"].lower()
    if "refund" in body:
        return Resolution(
            reply="(not sent: held for a person)",
            summary="Refund request",
            actions=[Action("refund", "last month")],
        )
    # In production this step inspects the client's machine. Here we record
    # what that inspection found.
    return Resolution(
        reply=("Nothing's broken. The chat app is running but its main window is "
               "closed, so your agent has nothing to read. I left it alone so it "
               "won't pop up on your call. When the call ends, click the app in "
               "your dock, then tell your agent to go ahead."),
        summary="App running with main window closed; reopen after the call.",
        evidence={"window_list": "chat app: menu-bar windows only",
                  "video_call": "in meeting, screen share possible"},
        actions=[Action("reply_in_thread"),
                 Action("edit_agent_instructions", "note: hold, tell owner, reopen after call")],
    )


def demo() -> int:
    d = tempfile.mkdtemp(prefix="escalation-desk-")
    inbox, outbox = os.path.join(d, "inbox.jsonl"), os.path.join(d, "outbox.jsonl")
    with open(inbox, "w") as f:
        for m in INBOX:
            f.write(json.dumps(m) + "\n")

    desk = Desk(Store(os.path.join(d, "desk.db")), JsonlSource(inbox), JsonlChannel(outbox))
    print("watcher opened tickets:", desk.watch_once())
    print("second pass (nothing new):", desk.watch_once())
    while desk.work_once(handler, worker="demo") is not None:
        pass

    print("\ntickets")
    for t in desk.store.tickets():
        print(f"  {t['code']}  {t['status']:<12} {t['summary']}")
    print("\noutbox")
    with open(outbox) as f:
        for line in f:
            m = json.loads(line)
            print(f"  -> {m['thread']}: {m['text'][:90]}")
    print(f"\nfiles in {d}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        sys.exit(demo())
    print("usage: python -m escalation_desk demo")
    sys.exit(2)
