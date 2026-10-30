import json
import os
import tempfile
import time
import unittest

from escalation_desk import Action, Desk, JsonlChannel, JsonlSource, Resolution, Store


def write(path, msgs):
    with open(path, "a") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")


def read(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def ok_handler(t):
    return Resolution(reply="fixed", summary="ok", evidence={"checked": True},
                      actions=[Action("reply_in_thread")])


class DeskTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.inbox = os.path.join(self.dir, "in.jsonl")
        self.outbox = os.path.join(self.dir, "out.jsonl")
        self.db = os.path.join(self.dir, "desk.db")
        self.desk = Desk(Store(self.db), JsonlSource(self.inbox), JsonlChannel(self.outbox))

    def msg(self, i, text, thread="t1"):
        return {"id": str(i), "thread": thread, "sender": "c", "text": text}

    def test_only_addressed_messages_escalate(self):
        write(self.inbox, [self.msg(1, "hey"), self.msg(2, "Axiom, help"), self.msg(3, "axiom: also")])
        self.assertEqual(len(self.desk.watch_once()), 2)

    def test_one_ticket_and_one_holding_line_per_message(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        self.desk.watch_once()
        # Simulate a lost cursor (crash/restart): the same message is seen again.
        self.desk.store.db.execute("DELETE FROM cursor")
        self.desk.watch_once()
        self.assertEqual(len(self.desk.store.tickets()), 1)
        self.assertEqual(len(read(self.outbox)), 1)

    def test_holding_line_recovers_after_crash_before_send(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        # Ticket exists but the holding line never went out.
        self.desk.store.open_ticket("1", "t1", "Axiom, help")
        self.desk.watch_once()
        self.assertEqual(len(read(self.outbox)), 1)

    def test_reply_sent_once_and_ticket_closed_with_evidence(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        self.desk.watch_once()
        tid = self.desk.work_once(ok_handler, worker="w")
        t = self.desk.store.ticket(tid)
        self.assertEqual(t["status"], "done")
        self.assertTrue(json.loads(t["evidence"])["checked"])
        self.assertEqual([m["text"] for m in read(self.outbox)][-1], "fixed")
        self.assertFalse(self.desk.send_once("reply:1", "t1", "fixed"))

    def test_gate_holds_money_and_sends_no_reply(self):
        write(self.inbox, [self.msg(1, "Axiom, refund me")])
        self.desk.watch_once()

        def refund(t):
            return Resolution(reply="refunded!", summary="refund",
                              actions=[Action("reply_in_thread"), Action("refund")])

        tid = self.desk.work_once(refund, worker="w")
        self.assertEqual(self.desk.store.ticket(tid)["status"], "needs_human")
        self.assertNotIn("refunded!", [m["text"] for m in read(self.outbox)])

    def test_unknown_action_fails_closed(self):
        write(self.inbox, [self.msg(1, "Axiom, do a thing")])
        self.desk.watch_once()
        tid = self.desk.work_once(lambda t: Resolution("x", "x", actions=[Action("launch_rocket")]), "w")
        self.assertEqual(self.desk.store.ticket(tid)["status"], "needs_human")

    def test_crashed_worker_lease_expires_and_ticket_is_retried(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        self.desk.watch_once()

        def boom(t):
            raise RuntimeError("worker died")

        self.desk.work_once(boom, worker="w1", lease_s=60)
        self.assertIsNone(self.desk.store.claim("w2"))  # still leased to w1
        # w1 is gone; let its lease run out.
        self.desk.store.db.execute("UPDATE tickets SET lease_expires=0")
        tid = self.desk.work_once(ok_handler, worker="w2")
        self.assertEqual(self.desk.store.ticket(tid)["status"], "done")

    def test_repeated_failure_goes_to_a_person(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        self.desk.watch_once()

        def boom(t):
            raise RuntimeError("nope")

        for _ in range(3):
            self.desk.work_once(boom, worker="w", lease_s=0)
            time.sleep(0.01)
        tid = self.desk.work_once(boom, worker="w", lease_s=0)
        self.assertEqual(self.desk.store.ticket(tid)["status"], "needs_human")

    def test_two_desks_share_one_database(self):
        write(self.inbox, [self.msg(1, "Axiom, help")])
        self.desk.watch_once()
        other = Desk(Store(self.db), JsonlSource(self.inbox), JsonlChannel(self.outbox))
        a = self.desk.store.claim("a")
        b = other.store.claim("b")
        self.assertIsNotNone(a)
        self.assertIsNone(b)


if __name__ == "__main__":
    unittest.main()
