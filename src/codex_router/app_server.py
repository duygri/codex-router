"""Fail-closed bridge from the local HTTP surface to Codex App Server."""

import json
import queue
import subprocess
import threading
import time
import uuid

from .model_catalog import is_safe_model_id


MAX_JSON_LINE_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 120
SAFE_APPROVAL_POLICY = "on-request"
SAFE_SANDBOX = "read-only"
APP_SERVER_APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
    "item/tool/call",
    "account/chatgptAuthTokens/refresh",
    "applyPatchApproval",
    "execCommandApproval",
}
READINESS_MODEL_METADATA_KEYS = {
    "additionalSpeedTiers",
    "availabilityNux",
    "defaultReasoningEffort",
    "defaultServiceTier",
    "description",
    "displayName",
    "hidden",
    "inputModalities",
    "isDefault",
    "serviceTiers",
    "supportedReasoningEfforts",
    "supportsPersonality",
    "upgrade",
    "upgradeInfo",
}


def _is_model_unavailable_error(method, error):
    if method != "thread/start" or not isinstance(error, dict):
        return False
    message = error.get("message")
    if not isinstance(message, str):
        return False
    lowered = message.lower()
    return "model" in lowered and any(
        marker in lowered for marker in ("not found", "not available", "unavailable", "unknown", "unsupported")
    )
UNSUPPORTED_REQUEST_KEYS = {
    "approvalPolicy",
    "approval_policy",
    "sandbox",
    "sandboxPolicy",
    "cwd",
    "permissions",
    "tools",
    "tool_choice",
    "functions",
    "function_call",
    "response_format",
}


class AppServerError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _EndOfStream:
    pass


_END_OF_STREAM = _EndOfStream()


class _AppServerSession:
    def __init__(self, command, process_factory, timeout, max_line_bytes):
        self.command = command
        self.process_factory = process_factory
        self.timeout = timeout
        self.max_line_bytes = max_line_bytes
        self.process = None
        self.messages = queue.Queue(maxsize=128)
        self.reader_thread = None
        self.write_lock = threading.Lock()
        self.closed = False

    def start(self):
        args = [self.command, "app-server", "--listen", "stdio://"]
        try:
            self.process = self.process_factory(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except FileNotFoundError:
            raise AppServerError(503, "codex_cli_not_found", "Codex CLI was not found")
        except (OSError, subprocess.SubprocessError):
            raise AppServerError(503, "codex_cli_unavailable", "Codex App Server could not be started")

        if self.process.poll() is not None:
            raise AppServerError(503, "app_server_unavailable", "Codex App Server exited before startup")

        self.reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader_thread.start()

    def _read_stdout(self):
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                if len(line) > self.max_line_bytes:
                    self.messages.put(AppServerError(502, "app_server_protocol_error", "Codex App Server returned an oversized message"))
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self.messages.put(AppServerError(502, "app_server_protocol_error", "Codex App Server returned invalid JSON"))
                    break
                if not isinstance(message, dict):
                    self.messages.put(AppServerError(502, "app_server_protocol_error", "Codex App Server returned an invalid message"))
                    break
                self.messages.put(message)
        except (OSError, ValueError):
            self.messages.put(AppServerError(502, "app_server_unavailable", "Codex App Server stopped unexpectedly"))
        finally:
            try:
                self.messages.put(_END_OF_STREAM, timeout=0.5)
            except queue.Full:
                pass

    def send(self, message):
        if self.closed or self.process is None or self.process.poll() is not None:
            raise AppServerError(502, "app_server_unavailable", "Codex App Server is unavailable")
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self.write_lock:
                self.process.stdin.write(encoded)
                self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise AppServerError(502, "app_server_unavailable", "Codex App Server is unavailable")

    def next_message(self, timeout):
        try:
            message = self.messages.get(timeout=max(0.01, timeout))
        except queue.Empty:
            raise AppServerError(504, "app_server_timeout", "Codex App Server did not respond in time")
        if isinstance(message, AppServerError):
            raise message
        if message is _END_OF_STREAM:
            raise AppServerError(502, "app_server_unavailable", "Codex App Server stopped unexpectedly")
        return message

    def reject_server_request(self, message):
        request_id = message.get("id")
        if request_id is None:
            return
        self.send({
            "id": request_id,
            "error": {
                "code": -32000,
                "message": "User approval and client-side tools are unavailable through codex-router",
            },
        })

    def request(self, request_id, method, params):
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self.next_message(deadline - time.monotonic())
            if "method" in message and "id" in message:
                self.reject_server_request(message)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                if _is_model_unavailable_error(method, message.get("error")):
                    raise AppServerError(503, "model_unavailable", "Requested Codex model is unavailable")
                raise AppServerError(502, "app_server_request_failed", "Codex App Server rejected the request")
            return message.get("result") or {}

    def interrupt(self, thread_id, turn_id):
        if self.closed or not thread_id or not turn_id:
            return
        try:
            self.send({
                "id": "interrupt-" + uuid.uuid4().hex,
                "method": "turn/interrupt",
                "params": {"threadId": thread_id, "turnId": turn_id},
            })
        except AppServerError:
            return

    def close(self, thread_id=None, turn_id=None):
        if self.closed:
            return
        if thread_id and turn_id and self.process is not None and self.process.poll() is None:
            self.interrupt(thread_id, turn_id)
        self.closed = True
        process = self.process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError, TimeoutError):
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError, TimeoutError):
                pass


class _MemoryResponse:
    def __init__(self, body, content_type="application/json", headers=None):
        self.status = 200
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }
        if headers:
            self.headers.update(headers)
        self._body = body

    def read(self, size=-1):
        if size == -1:
            body, self._body = self._body, b""
            return body
        body, self._body = self._body[:size], self._body[size:]
        return body


class _CompletionResponse:
    def __init__(self, session, thread_id, turn_id, model, stream, release):
        self.status = 200
        self.headers = {"Content-Type": "text/event-stream" if stream else "application/json"}
        self.session = session
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.model = model or "codex"
        self.stream = stream
        self.release = release
        self.closed = False
        self.completed = False
        self.completion_id = "chatcmpl-" + uuid.uuid4().hex
        self.created = int(time.time())
        self.usage_callback = None

    def set_usage_callback(self, callback):
        self.usage_callback = callback

    def _sse(self, payload):
        return ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")

    def _error_sse(self, error):
        return self._sse({
            "error": {
                "code": error.code,
                "message": error.message,
                "type": "codex_router_error",
            },
        })

    def _chunk(self, delta, finish_reason=None):
        return self._sse({
            "id": self.completion_id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }],
        })

    def iter_bytes(self):
        text_parts = []
        try:
            if self.stream:
                yield self._chunk({"role": "assistant"})
            deadline = time.monotonic() + self.session.timeout
            while True:
                message = self.session.next_message(deadline - time.monotonic())
                if "method" in message and "id" in message:
                    self.session.reject_server_request(message)
                    self.session.interrupt(self.thread_id, self.turn_id)
                    raise AppServerError(403, "approval_required", "Codex requested an approval unavailable through codex-router")
                method = message.get("method")
                params = message.get("params") or {}
                if method == "item/agentMessage/delta":
                    if params.get("threadId") != self.thread_id or params.get("turnId") != self.turn_id:
                        continue
                    delta = params.get("delta")
                    if not isinstance(delta, str):
                        raise AppServerError(502, "app_server_protocol_error", "Codex App Server returned an invalid text delta")
                    text_parts.append(delta)
                    if self.stream:
                        yield self._chunk({"content": delta})
                    continue
                if method == "thread/tokenUsage/updated":
                    usage = params.get("tokenUsage") or params.get("usage")
                    if callable(self.usage_callback):
                        self.usage_callback(usage)
                    continue
                if method != "turn/completed":
                    continue
                if params.get("threadId") != self.thread_id:
                    continue
                turn = params.get("turn") or {}
                status = turn.get("status")
                self.completed = True
                if status != "completed":
                    raise AppServerError(502, "app_server_turn_failed", "Codex turn did not complete successfully")
                if self.stream:
                    yield self._chunk({}, "stop")
                    yield b"data: [DONE]\n\n"
                else:
                    body = {
                        "id": self.completion_id,
                        "object": "chat.completion",
                        "created": self.created,
                        "model": self.model,
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": "".join(text_parts)},
                            "finish_reason": "stop",
                        }],
                    }
                    yield json.dumps(body, separators=(",", ":")).encode("utf-8")
                return
        except AppServerError as error:
            if self.stream:
                yield self._error_sse(error)
                yield b"data: [DONE]\n\n"
                return
            raise
        finally:
            self.close()

    def read(self, size=-1):
        body = b"".join(self.iter_bytes())
        if size == -1:
            return body
        return body[:size]

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.session.close(self.thread_id if not self.completed else None, self.turn_id if not self.completed else None)
        self.release()


class AppServerBridge:
    """Use one short-lived, isolated Codex App Server session per request."""

    def __init__(self, command="codex", process_factory=None, timeout=DEFAULT_TIMEOUT_SECONDS, max_line_bytes=MAX_JSON_LINE_BYTES, queue_size=2, queue_timeout=30.0):
        self.command = command or "codex"
        self.process_factory = process_factory or subprocess.Popen
        self.timeout = timeout
        self.max_line_bytes = max_line_bytes
        self.queue_size = max(0, int(queue_size))
        self.queue_timeout = max(0.1, float(queue_timeout))
        self.admission = threading.BoundedSemaphore(1)
        self.waiting = threading.BoundedSemaphore(self.queue_size)

    def _acquire(self):
        if self.admission.acquire(blocking=False):
            return
        if not self.waiting.acquire(blocking=False):
            raise AppServerError(429, "app_server_queue_full", "Codex Router request queue is full")
        try:
            if not self.admission.acquire(timeout=self.queue_timeout):
                raise AppServerError(429, "app_server_queue_timeout", "Codex Router request queue timed out")
        finally:
            self.waiting.release()

    def _new_session(self, timeout=None, max_line_bytes=None):
        session = _AppServerSession(
            self.command,
            self.process_factory,
            self.timeout if timeout is None else timeout,
            self.max_line_bytes if max_line_bytes is None else max_line_bytes,
        )
        try:
            session.start()
            session.request(1, "initialize", {
                "clientInfo": {
                    "name": "codex-router",
                    "title": "Codex Router",
                    "version": "0.1.0",
                },
            })
            session.send({"method": "initialized", "params": {}})
            return session
        except Exception:
            session.close()
            raise

    @staticmethod
    def _prompt_from_messages(messages):
        if not isinstance(messages, list) or not messages:
            raise AppServerError(400, "invalid_messages", "messages must be a non-empty array")
        rendered = []
        for message in messages:
            if not isinstance(message, dict):
                raise AppServerError(400, "invalid_messages", "messages must contain objects")
            role = message.get("role")
            content = message.get("content")
            if role not in ("system", "user", "assistant") or not isinstance(content, str):
                raise AppServerError(400, "unsupported_message", "Only text system, user, and assistant messages are supported")
            rendered.append("[{}]\n{}".format(role, content))
        return "\n\n".join(rendered)

    @staticmethod
    def _validate_payload(payload):
        if not isinstance(payload, dict):
            raise AppServerError(400, "invalid_payload", "Request body must be a JSON object")
        dangerous = UNSUPPORTED_REQUEST_KEYS.intersection(payload)
        if dangerous:
            raise AppServerError(400, "unsafe_request_options", "Request options cannot override Codex permissions")
        allowed = {"model", "messages", "stream"}
        unknown = set(payload).difference(allowed)
        if unknown:
            raise AppServerError(400, "unsupported_request_options", "Request contains unsupported options")
        model = payload.get("model")
        if model is not None and (not isinstance(model, str) or not model or len(model) > 256 or "\n" in model or "\r" in model):
            raise AppServerError(400, "invalid_model", "model must be a short text value")
        if "stream" in payload and not isinstance(payload["stream"], bool):
            raise AppServerError(400, "invalid_stream", "stream must be boolean")
        return model, bool(payload.get("stream", False)), AppServerBridge._prompt_from_messages(payload.get("messages"))

    def start_chat(self, payload):
        model, stream, prompt = self._validate_payload(payload)
        self._acquire()
        try:
            session = self._new_session()
            params = {
                "approvalPolicy": SAFE_APPROVAL_POLICY,
                "sandbox": SAFE_SANDBOX,
                "ephemeral": True,
            }
            if model:
                params["model"] = model
            thread_result = session.request(2, "thread/start", params)
            thread = thread_result.get("thread") if isinstance(thread_result, dict) else None
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str) or not thread_id:
                raise AppServerError(502, "app_server_protocol_error", "Codex App Server returned no thread id")
            turn_result = session.request(3, "turn/start", {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
            })
            turn = turn_result.get("turn") if isinstance(turn_result, dict) else None
            turn_id = turn.get("id") if isinstance(turn, dict) else None
            if not isinstance(turn_id, str) or not turn_id:
                raise AppServerError(502, "app_server_protocol_error", "Codex App Server returned no turn id")
            return _CompletionResponse(session, thread_id, turn_id, model, stream, self.admission.release)
        except Exception:
            self.admission.release()
            raise

    @staticmethod
    def _validate_readiness_models(models):
        if not isinstance(models, list):
            raise AppServerError(502, "app_server_protocol_error", "Codex App Server returned an invalid model list")
        if not models:
            raise AppServerError(503, "model_catalog_empty", "Codex returned no available models")
        allowed_keys = {"id", "model"}.union(READINESS_MODEL_METADATA_KEYS)
        validated = []
        for item in models:
            if not isinstance(item, dict) or set(item).difference(allowed_keys):
                raise AppServerError(503, "model_catalog_invalid", "Codex returned an invalid model catalog")
            has_id = "id" in item
            has_model = "model" in item
            if not has_id and not has_model:
                raise AppServerError(503, "model_catalog_invalid", "Codex returned an invalid model catalog")
            if has_id and not is_safe_model_id(item.get("id")):
                raise AppServerError(503, "model_catalog_invalid", "Codex returned an invalid model catalog")
            if has_model and not is_safe_model_id(item.get("model")):
                raise AppServerError(503, "model_catalog_invalid", "Codex returned an invalid model catalog")
            if has_id and has_model and item["id"] != item["model"]:
                raise AppServerError(503, "model_catalog_invalid", "Codex returned an invalid model catalog")
            validated.append(dict(item))
        return validated

    def probe_models(self, timeout=3.0):
        """Run a read-only initialize/model-list probe in one process."""
        session = None
        try:
            session = self._new_session(timeout=timeout, max_line_bytes=1024 * 1024)
            result = session.request(2, "model/list", {"limit": 100})
            models = result.get("data") if isinstance(result, dict) else None
            return self._validate_readiness_models(models)
        finally:
            if session is not None:
                session.close()

    def list_models(self):
        models = self.list_model_items()
        data = []
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("id") or model.get("model")
            if isinstance(model_id, str) and model_id:
                data.append({"id": model_id, "object": "model", "created": 0, "owned_by": "codex"})
        body = json.dumps({"object": "list", "data": data}, separators=(",", ":")).encode("utf-8")
        return _MemoryResponse(body)

    def list_model_items(self):
        self._acquire()
        session = None
        try:
            session = self._new_session()
            result = session.request(2, "model/list", {"limit": 100})
            models = result.get("data") if isinstance(result, dict) else None
            if not isinstance(models, list):
                raise AppServerError(502, "app_server_protocol_error", "Codex App Server returned an invalid model list")
            return models
        finally:
            if session is not None:
                session.close()
            self.admission.release()

    def close(self):
        return None
