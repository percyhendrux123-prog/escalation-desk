# escalation-desk

When an agent gets stuck, someone has to answer. This is the loop that does it without a person sitting in a chat window.

I run two businesses and two client deployments on a team of Hermes agents. Each client has their own agent on their own Mac. When a client's agent hits something it can't handle, it messages my operator agent. This repo is a clean, standalone version of the loop that takes it from there: catch the escalation, tell the person it landed, work the problem, check what the fix is allowed to do, reply once, and keep the evidence.

## A real night

At 6:31 PM a client's agent wrote in: the desktop chat app wasn't showing a usable window during an intake, so it was holding a launch post rather than guessing where to send it. The client was on a video call.

- 6:35 PM: the watcher saw the message and sent a holding line. A ticket opened.
- A worker picked up the ticket and checked the client's machine. The app was running, but its main window was closed. Nothing was broken.
- It didn't reopen the window, because that might have popped up on a screen share.
- 6:38 PM: one reply went out explaining what to click after the call. A note went into the agent's instructions, with a backup, so it can handle this on its own next time. The ticket closed with the window list and call state as evidence.

Nobody had a chat open. `python -m escalation_desk demo` replays a version of that night.

## How it works

```
 inbound messages ──> WATCHER ──> holding line (once)
                          │
                          └──> ticket (one per message, ever)
                                   │
                              DISPATCHER  (claims with a lease)
                                   │
                               handler  ──> reply + evidence + actions
                                   │
                                 GATE
                       ┌───────────┴───────────┐
                  all allowed              anything held
                       │                       │
              reply sent (once)          needs_human, no reply
              ticket done + evidence     that claims it's done
```

- **Watcher** (`Desk.watch_once`) reads new messages after a saved cursor. Only messages addressed to the operator (`Axiom, ...`, `Operator: ...`) escalate. Change the trigger to fit your setup.
- **Dispatcher** (`Desk.work_once`) claims a ticket inside a database transaction, so two workers can't take the same one. The claim is a lease. If a worker dies, the lease runs out and another worker retries the ticket. After three failed attempts it goes to a person.
- **Gate** (`gate.review`) sorts each action the handler wants to take. Reversible, private work runs on its own. Anything that moves money, deletes data, makes a new price or promise, contacts a stranger, or deploys to production waits for a human. An action the gate doesn't recognize also waits. It fails closed.

## What it promises

| Promise | How |
|---|---|
| One ticket per escalation | `UNIQUE` on the source message id |
| No double-texting | every send reserves an idempotency key first; a repeat send is a no-op |
| Holding line survives a crash | the send is retried on every pass and the key keeps it to one |
| Crashed worker doesn't strand a ticket | lease expiry hands it to the next worker |
| No silent consequential action | the gate holds it and the ticket goes to `needs_human` |
| An evidence trail | every state change is a row in `events`; closed tickets carry their evidence |

**Tradeoff, on purpose:** sends are at-most-once. If the process dies between reserving a send and the channel accepting it, that message is not retried. For client messaging I would rather miss one message and see it in the log than send it twice.

## What it doesn't do

- It doesn't decide what the fix is. That's your handler, usually an agent with tools. This repo is the part around it that keeps it safe and observable.
- The included source and channel are JSONL files so it runs anywhere. In production I read iMessage on a Mac and reply through it. Write a class with `since(last_id)` for your source and `send(thread, text)` for your channel.
- No scheduler. Run `watch_once` and `work_once` from launchd, cron, systemd, or a loop.

## Run it

Python 3.9+, standard library only.

```sh
python3 -m escalation_desk demo
python3 -m unittest -v
```

## Use it

```python
from escalation_desk import Action, Desk, JsonlChannel, JsonlSource, Resolution, Store

desk = Desk(Store("desk.db"), JsonlSource("inbox.jsonl"), JsonlChannel("outbox.jsonl"))

def handler(ticket):
    # look into ticket["body"], fix what you can, report what you saw
    return Resolution(
        reply="Fixed. Here's what happened...",
        summary="one line for the log",
        evidence={"checked": "what you actually observed"},
        actions=[Action("reply_in_thread")],
    )

desk.watch_once()
desk.work_once(handler)
```

## License

MIT
