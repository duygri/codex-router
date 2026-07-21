import threading
import unittest

from codex_router.config import RouterConfig
from codex_router.readiness import CheckResult, ReadinessProbe, doctor_report


ROUTER_KEY = "router-secret-0123456789-0123456789-0123456789"


class ReadinessProbeTests(unittest.TestCase):
    def real_config(self):
        return RouterConfig(adapter_version="real-v1", router_api_key=ROUTER_KEY)

    def test_real_report_has_exact_safe_four_check_envelope(self):
        probe = ReadinessProbe(
            self.real_config(),
            cli_check=lambda: CheckResult.ok("Codex CLI is available", version="0.145.0-alpha.18"),
            app_server_check=lambda: CheckResult.ok("Codex models are available", model_count=2),
        )

        report = probe.check().to_dict()

        self.assertEqual(report["status"], "ready")
        self.assertEqual(set(report["checks"]), {"config", "codex_cli", "app_server", "model_catalog"})
        self.assertEqual(report["checks"]["codex_cli"]["version"], "0.145.0-alpha.18")
        self.assertEqual(report["checks"]["model_catalog"]["model_count"], 2)
        self.assertNotIn("router-secret", str(report))

    def test_synthetic_report_marks_codex_checks_skipped(self):
        probe = ReadinessProbe(RouterConfig(adapter_version="synthetic-v1", router_api_key=ROUTER_KEY))

        report = probe.check().to_dict()

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["checks"]["config"]["code"], "ok")
        for name in ("codex_cli", "app_server", "model_catalog"):
            self.assertEqual(report["checks"][name], {
                "ok": True,
                "code": "skipped",
                "message": "Not required for synthetic-v1",
            })

    def test_not_ready_result_is_cached_until_ttl_expires(self):
        now = [100.0]
        calls = []

        def app_check():
            calls.append(True)
            return CheckResult.failure("app_server_unavailable", "Codex App Server is unavailable")

        probe = ReadinessProbe(
            self.real_config(),
            cli_check=lambda: CheckResult.ok("Codex CLI is available", version="0.145.0-alpha.18"),
            app_server_check=app_check,
            clock=lambda: now[0],
        )

        self.assertEqual(probe.check().status, "not_ready")
        self.assertEqual(probe.check().status, "not_ready")
        self.assertEqual(len(calls), 1)
        now[0] = 110.1
        self.assertEqual(probe.check().status, "not_ready")
        self.assertEqual(len(calls), 2)

    def test_waiter_timeout_is_not_cached_and_worker_populates_cache(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def app_check():
            calls.append(True)
            started.set()
            release.wait(1)
            return CheckResult.ok("Codex models are available", model_count=1)

        probe = ReadinessProbe(
            self.real_config(),
            cli_check=lambda: CheckResult.ok("Codex CLI is available", version="0.145.0-alpha.18"),
            app_server_check=app_check,
            waiter_timeout=0.01,
        )
        first = {}
        worker = threading.Thread(target=lambda: first.setdefault("report", probe.check()))
        worker.start()
        self.assertTrue(started.wait(1))

        timed_out = probe.check().to_dict()

        self.assertEqual(timed_out["status"], "not_ready")
        self.assertEqual(timed_out["checks"]["app_server"]["code"], "readiness_wait_timeout")
        release.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(probe.check().status, "ready")
        self.assertEqual(len(calls), 1)

    def test_doctor_report_is_independent_and_uncached(self):
        calls = []
        config = self.real_config()

        def app_check():
            calls.append(True)
            return CheckResult.ok("Codex models are available", model_count=1)

        report = doctor_report(
            config,
            cli_check=lambda: CheckResult.ok("Codex CLI is available", version="0.145.0-alpha.18"),
            app_server_check=app_check,
        )

        self.assertEqual(report.status, "ready")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
