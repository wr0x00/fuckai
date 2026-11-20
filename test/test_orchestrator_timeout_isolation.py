from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fuckai.client import ChatClient
from fuckai.orchestrator import Orchestrator


class OrchestratorTimeoutIsolationTests(unittest.TestCase):
    def test_concurrent_batches_keep_independent_timeouts(self):
        attack_client = ChatClient("", "", "")
        target_client = ChatClient("", "", "")
        orchestrator = Orchestrator.__new__(Orchestrator)
        orchestrator.attack_client = attack_client
        orchestrator.target_client = target_client
        orchestrator.converter = SimpleNamespace(attack=attack_client)
        orchestrator.scorer = SimpleNamespace(judge=attack_client)

        started = {
            "short-timeout": threading.Event(),
            "long-timeout": threading.Event(),
        }
        both_started = threading.Barrier(2)
        observed = {}
        observed_lock = threading.Lock()

        def fake_run(instance, objective, *args, **kwargs):
            started[objective].set()
            both_started.wait(timeout=5)
            with observed_lock:
                observed[objective] = (
                    instance.attack_client.timeout,
                    instance.target_client.timeout,
                )
            return {"success": False}

        def run_batch(objective, timeout):
            return orchestrator.run_batch(
                [objective], ["direct"], verbose=False, concurrency=1, timeout=timeout
            )

        with patch.object(Orchestrator, "run", fake_run):
            short_thread = threading.Thread(target=run_batch, args=("short-timeout", 15))
            long_thread = threading.Thread(target=run_batch, args=("long-timeout", 45))
            short_thread.start()
            self.assertTrue(started["short-timeout"].wait(timeout=5))
            long_thread.start()
            short_thread.join(timeout=10)
            long_thread.join(timeout=10)

        self.assertFalse(short_thread.is_alive())
        self.assertFalse(long_thread.is_alive())
        self.assertEqual(observed["short-timeout"], (15, 15))
        self.assertEqual(observed["long-timeout"], (45, 45))
        self.assertEqual(attack_client.timeout, 120)
        self.assertEqual(target_client.timeout, 120)


if __name__ == "__main__":
    unittest.main()