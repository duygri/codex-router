import json
import queue
import tempfile
import threading
import unittest

from codex_router.app_server import AppServerBridge, AppServerError


class _FakeStdout:
    def __init__(self, owner):
        self.owner = owner

    def readline(self):
        value = self.owner.output.get()
        if value is None:
            return b""
        return value


class _FakeStdin:
    def __init__(self, owner):
        self.owner = owner

    def write(self, data):
        message = json.loads(data.decode("utf-8"))
        self.owner.requests.append(message)
        self.owner.handle(message)
        return len(data)

    def flush(self):
        return None


class _FakeProcess:
    def __init__(self, events=None, models=None, thread_error=False):
        self.output = queue.Queue()
        self.requests = []
        self.events = events or []
        self.models = models or [{"id": "gpt-test", "model": "gpt-test"}]
        self.thread_error = thread_error
        self.returncode = None
        self.stdin = _FakeStdin(self)
        self.stdout = _FakeStdout(self)
        self.terminated = False
        self.killed = False

    def emit(self, message):
        self.output.put((json.dumps(message) + "\n").encode("utf-8"))

    def handle(self, message):
        method = message.get("method")
        if method == "initialize":
            self.emit({"id": message["id"], "result": {"userAgent": "codex-test"}})
        elif method == "thread/start":
            if self.thread_error:
                self.emit({"id": message["id"], "error": {"code": -32600, "message": "requested model not found"}})
                return
            self.emit({
                "id": message["id"],
                "result": {"thread": {"id": "thr_test"}},
            })
        elif method == "model/list":
            self.emit({"id": message["id"], "result": {"data": self.models}})
        elif method == "turn/start":
            self.emit({"id": message["id"], "result": {"turn": {"id": "turn_test"}}})
            for event in self.events:
                self.emit(event)
        elif method == "turn/interrupt":
            self.emit({"id": message["id"], "result": {}})

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.output.put(None)

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.output.put(None)

    def wait(self, timeout=None):
        return self.returncode


class AppServerBridgeTests(unittest.TestCase):
    def make_bridge(self, events=None, models=None, queue_size=2, queue_timeout=1, thread_error=False):
        fake = _FakeProcess(events=events, models=models, thread_error=thread_error)
        bridge = AppServerBridge(
            command="codex-test",
            process_factory=lambda _args, **_kwargs: fake,
            timeout=1,
            queue_size=queue_size,
            queue_timeout=queue_timeout,
        )
        self.addCleanup(bridge.close)
        return bridge, fake

    def test_thread_policy_is_fixed_and_request_cannot_override_it(self):
        bridge, fake = self.make_bridge([
            {"method": "turn/completed", "params": {
                "threadId": "thr_test",
                "turn": {"id": "turn_test", "status": "completed"},
            }},
        ])
        response = bridge.start_chat({
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        })
        list(response.iter_bytes())
        thread_request = next(item for item in fake.requests if item.get("method") == "thread/start")
        self.assertEqual(thread_request["params"]["approvalPolicy"], "on-request")
        self.assertEqual(thread_request["params"]["sandbox"], "read-only")
        self.assertTrue(thread_request["params"]["ephemeral"])

        with self.assertRaises(AppServerError) as raised:
            bridge.start_chat({
                "messages": [{"role": "user", "content": "hello"}],
                "approvalPolicy": "never",
            })
        self.assertEqual(raised.exception.code, "unsafe_request_options")

        with self.assertRaises(AppServerError) as raised:
            bridge.start_chat({
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [],
            })
        self.assertEqual(raised.exception.code, "unsafe_request_options")

    def test_stream_only_forwards_agent_text_delta(self):
        bridge, _ = self.make_bridge([
            {"method": "item/started", "params": {"item": {"type": "commandExecution"}}},
            {"method": "item/agentMessage/delta", "params": {
                "threadId": "thr_test", "turnId": "turn_test", "itemId": "item_test", "delta": "hello",
            }},
            {"method": "item/commandExecution/outputDelta", "params": {"delta": "secret command output"}},
            {"method": "turn/completed", "params": {
                "threadId": "thr_test",
                "turn": {"id": "turn_test", "status": "completed"},
            }},
        ])
        response = bridge.start_chat({
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        })
        body = b"".join(response.iter_bytes())
        self.assertIn(b'"content":"hello"', body)
        self.assertIn(b"[DONE]", body)
        self.assertNotIn(b"secret command output", body)

    def test_token_usage_notification_is_forwarded_as_numeric_usage_only(self):
        bridge, _ = self.make_bridge([
            {"method": "thread/tokenUsage/updated", "params": {
                "threadId": "thr_test",
                "tokenUsage": {"total": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10}},
            }},
            {"method": "item/agentMessage/delta", "params": {
                "threadId": "thr_test", "turnId": "turn_test", "delta": "ok",
            }},
            {"method": "turn/completed", "params": {
                "threadId": "thr_test",
                "turn": {"id": "turn_test", "status": "completed"},
            }},
        ])
        usage = []
        response = bridge.start_chat({
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        })
        response.set_usage_callback(usage.append)
        list(response.iter_bytes())
        self.assertEqual(usage, [{"total": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10}}])

    def test_approval_request_fails_closed_without_leaking_command(self):
        bridge, fake = self.make_bridge([
            {"id": 99, "method": "item/commandExecution/requestApproval", "params": {
                "threadId": "thr_test", "turnId": "turn_test", "command": "cat secret.txt",
            }},
            {"method": "turn/completed", "params": {
                "threadId": "thr_test",
                "turn": {"id": "turn_test", "status": "interrupted"},
            }},
        ])
        response = bridge.start_chat({
            "messages": [{"role": "user", "content": "read the repo"}],
            "stream": True,
        })
        body = b"".join(response.iter_bytes())
        self.assertIn(b"approval_required", body)
        self.assertNotIn(b"cat secret.txt", body)
        denied = next(item for item in fake.requests if item.get("id") == 99)
        self.assertEqual(denied["error"]["code"], -32000)

    def test_model_list_maps_to_openai_shape(self):
        bridge, _ = self.make_bridge(models=[
            {"id": "gpt-test", "model": "gpt-test", "displayName": "Test"},
        ])
        response = bridge.list_models()
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["object"], "list")
        self.assertEqual(payload["data"][0]["id"], "gpt-test")
        self.assertEqual(payload["data"][0]["object"], "model")

    def test_process_crash_is_safe_error(self):
        bridge, fake = self.make_bridge([])
        fake.returncode = 17
        with self.assertRaises(AppServerError) as raised:
            bridge.start_chat({"messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(raised.exception.code, "app_server_unavailable")

    def test_close_interrupts_active_turn_before_terminating_process(self):
        bridge, fake = self.make_bridge([])
        response = bridge.start_chat({"messages": [{"role": "user", "content": "hello"}]})
        response.close()
        interrupts = [item for item in fake.requests if item.get("method") == "turn/interrupt"]
        self.assertEqual(len(interrupts), 1)

    def test_rejects_new_work_when_bounded_queue_is_full(self):
        bridge, _ = self.make_bridge(queue_size=0)
        self.assertTrue(bridge.admission.acquire())
        try:
            with self.assertRaises(AppServerError) as raised:
                bridge._acquire()
            self.assertEqual(raised.exception.code, "app_server_queue_full")
        finally:
            bridge.admission.release()

    def test_bounded_queue_times_out_without_leaking_a_waiter_slot(self):
        bridge, _ = self.make_bridge(queue_size=1, queue_timeout=0.01)
        self.assertTrue(bridge.admission.acquire())
        try:
            with self.assertRaises(AppServerError) as raised:
                bridge._acquire()
            self.assertEqual(raised.exception.code, "app_server_queue_timeout")
            self.assertTrue(bridge.waiting.acquire(blocking=False))
            bridge.waiting.release()
        finally:
            bridge.admission.release()

    def test_classifies_only_model_start_failures_as_model_unavailable(self):
        bridge, _ = self.make_bridge(thread_error=True)
        with self.assertRaises(AppServerError) as raised:
            bridge.start_chat({"model": "gpt-missing", "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(raised.exception.code, "model_unavailable")


if __name__ == "__main__":
    unittest.main()
