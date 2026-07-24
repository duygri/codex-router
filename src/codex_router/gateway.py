"""OpenAI-compatible upstream transport with fail-closed auth handling."""

import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .auth import RefreshOutcome, SessionStatus
from .app_server import AppServerBridge, AppServerError, _MemoryResponse
from .model_catalog import ModelCatalog, ModelCatalogError


class GatewayError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GatewayError(502, "upstream_redirect_blocked", "Upstream redirects are disabled")


class _TrackedResponse:
    def __init__(self, response, usage_handle):
        self.response = response
        self.usage_handle = usage_handle
        self.status = getattr(response, "status", 200)
        self.headers = getattr(response, "headers", {})

    def read(self, size=-1):
        try:
            body = self.response.read(size)
            self.usage_handle.complete("completed")
            return body
        except Exception:
            self.usage_handle.complete("failed")
            raise

    def iter_bytes(self):
        try:
            if hasattr(self.response, "iter_bytes"):
                for chunk in self.response.iter_bytes():
                    yield chunk
            else:
                body = self.response.read()
                if body:
                    yield body
            self.usage_handle.complete("completed")
        except GeneratorExit:
            self.usage_handle.complete("cancelled")
            raise
        except Exception:
            self.usage_handle.complete("failed")
            raise
        finally:
            self._close_response()

    def _close_response(self):
        close = getattr(self.response, "close", None)
        if close:
            close()

    def close(self):
        self._close_response()
        self.usage_handle.complete("cancelled")


class _ResponsesResponse:
    """Translate the text-only Chat Completions stream to Responses events."""

    def __init__(self, response, model, stream):
        self.response = response
        self.model = model or "codex"
        self.stream = stream
        self.status = getattr(response, "status", 200)
        self.headers = {"Content-Type": "text/event-stream" if stream else "application/json"}
        self.response_id = "resp_" + uuid.uuid4().hex
        self.created_at = int(time.time())
        self.text = ""
        self.closed = False
        self.completed = False

    def _event(self, event_type, payload):
        body = dict(payload)
        body["type"] = event_type
        return ("event: %s\ndata: %s\n\n" % (
            event_type,
            json.dumps(body, separators=(",", ":")),
        )).encode("utf-8")

    def set_usage_callback(self, callback):
        setter = getattr(self.response, "set_usage_callback", None)
        if setter:
            setter(callback)

    def _response_payload(self, status="completed"):
        payload = {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "model": self.model,
            "output_text": self.text,
            "usage": None,
        }
        if status == "completed":
            payload["output"] = [{
                "id": "msg_" + self.response_id[5:],
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": self.text,
                    "annotations": [],
                }],
            }]
        else:
            payload["output"] = []
        return payload

    @staticmethod
    def _chat_text(body):
        try:
            payload = json.loads(body.decode("utf-8"))
            choice = payload.get("choices", [{}])[0]
            message = choice.get("message", {})
            text = message.get("content", "")
        except (UnicodeDecodeError, ValueError, AttributeError, IndexError, TypeError):
            raise GatewayError(502, "upstream_protocol_error", "Codex returned an invalid text response")
        if not isinstance(text, str):
            raise GatewayError(502, "upstream_protocol_error", "Codex returned an invalid text response")
        return payload.get("model") or "codex", text

    def _read_raw(self):
        if hasattr(self.response, "iter_bytes"):
            return b"".join(self.response.iter_bytes())
        return self.response.read()

    def read(self, size=-1):
        if self.stream:
            body = b"".join(self.iter_bytes())
        else:
            raw = self._read_raw()
            upstream_model, self.text = self._chat_text(raw)
            if self.model == "codex" and upstream_model:
                self.model = upstream_model
            body = json.dumps(self._response_payload(), separators=(",", ":")).encode("utf-8")
            self.completed = True
            self.close()
        if size == -1:
            return body
        return body[:size]

    def iter_bytes(self):
        if not self.stream:
            yield self.read()
            return
        try:
            yield self._event("response.created", {"response": self._response_payload("in_progress")})
            buffer = ""
            for chunk in self.response.iter_bytes() if hasattr(self.response, "iter_bytes") else iter((self.response.read(),)):
                if not chunk:
                    continue
                buffer += chunk.decode("utf-8")
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    data_lines = [line[6:] for line in block.splitlines() if line.startswith("data:")]
                    if not data_lines:
                        continue
                    data = "\n".join(data_lines)
                    if data == "[DONE]":
                        continue
                    try:
                        payload = json.loads(data)
                    except ValueError:
                        raise GatewayError(502, "upstream_protocol_error", "Codex returned an invalid stream event")
                    if isinstance(payload, dict) and payload.get("error"):
                        yield self._event("error", {"error": {"message": "Codex returned an error"}})
                        return
                    choices = payload.get("choices", []) if isinstance(payload, dict) else []
                    delta = choices[0].get("delta", {}) if choices else {}
                    content = delta.get("content") if isinstance(delta, dict) else None
                    if isinstance(content, str) and content:
                        self.text += content
                        yield self._event("response.output_text.delta", {
                            "delta": content,
                            "item_id": "msg_" + self.response_id[5:],
                            "output_index": 0,
                            "content_index": 0,
                        })
                    finish = choices[0].get("finish_reason") if choices else None
                    if finish == "stop":
                        yield self._event("response.output_text.done", {
                            "text": self.text,
                            "item_id": "msg_" + self.response_id[5:],
                            "output_index": 0,
                            "content_index": 0,
                        })
                        self.completed = True
                        yield self._event("response.completed", {"response": self._response_payload()})
                        return
            if buffer.strip():
                raise GatewayError(502, "upstream_protocol_error", "Codex returned an incomplete stream")
            if not self.completed:
                yield self._event("response.completed", {"response": self._response_payload()})
                self.completed = True
        except GatewayError as error:
            yield self._event("error", {"error": {"code": error.code, "message": error.message}})
            yield self._event("response.failed", {
                "response": self._response_payload("failed"),
                "error": {"code": error.code, "message": error.message},
            })
        except UnicodeDecodeError:
            yield self._event("error", {"error": {"code": "upstream_protocol_error", "message": "Codex returned an invalid stream event"}})
        except GeneratorExit:
            raise
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        close = getattr(self.response, "close", None)
        if close:
            close()


def _is_loopback(hostname):
    return (hostname or "").lower().rstrip(".") in ("127.0.0.1", "localhost", "::1")


def _validate_upstream_url(value):
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise GatewayError(503, "unsafe_upstream", "Configured upstream URL is invalid")
    if parsed.username or parsed.password or parsed.fragment or parsed.query or not parsed.hostname:
        raise GatewayError(503, "unsafe_upstream", "Configured upstream URL is unsafe")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "api.openai.com":
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise GatewayError(503, "unsafe_upstream", "OpenAI upstream must use HTTPS")
        return
    if _is_loopback(hostname):
        if parsed.scheme not in ("http", "https"):
            raise GatewayError(503, "unsafe_upstream", "Loopback upstream scheme is invalid")
        return
    if parsed.scheme == "http":
        raise GatewayError(503, "insecure_upstream", "Non-loopback upstream must use HTTPS")
    raise GatewayError(503, "unsafe_upstream", "Remote custom upstreams are disabled")


class Gateway:
    def __init__(self, auth_adapter, upstream_url, opener=None, timeout=30, app_server=None, app_server_command="codex", app_server_queue_size=2, app_server_queue_timeout=30.0, model_catalog=None, usage_tracker=None, model_fallbacks=()):
        self.auth_adapter = auth_adapter
        self.upstream_url = (upstream_url or "").rstrip("/")
        self.opener = opener or build_opener(_NoRedirectHandler())
        self.timeout = timeout
        self.app_server = app_server or (
            AppServerBridge(
                command=app_server_command,
                timeout=timeout,
                queue_size=app_server_queue_size,
                queue_timeout=app_server_queue_timeout,
            )
            if getattr(auth_adapter, "adapter_version", "") == "real-v1"
            else None
        )
        self.model_catalog = model_catalog
        if self.model_catalog is None and isinstance(self.app_server, AppServerBridge):
            self.model_catalog = ModelCatalog(self.app_server.list_model_items)
        self.usage_tracker = usage_tracker
        self.model_fallbacks = tuple(model_fallbacks or ())

    def _authenticate(self):
        loaded = self.auth_adapter.load_session()
        refreshed = self.auth_adapter.refresh_if_needed(loaded)
        if refreshed.outcome in (RefreshOutcome.VALID, RefreshOutcome.REFRESHED):
            return refreshed.session, loaded.fingerprint
        if loaded.status == SessionStatus.MISSING:
            raise GatewayError(401, "auth_required", "Run codex login before using the router")
        if refreshed.outcome == RefreshOutcome.REAUTH_REQUIRED or loaded.status == SessionStatus.EXPIRED:
            raise GatewayError(401, "auth_expired", "Run codex login to reauthenticate")
        raise GatewayError(503, "unsupported_codex_version", "Codex authentication format is not supported")

    def ensure_session_current(self, fingerprint):
        if not fingerprint or self.auth_adapter.current_fingerprint() != fingerprint:
            raise GatewayError(401, "auth_expired", "Codex session changed; reauthenticate and retry")

    def open_upstream(self, method, path, payload=None):
        if getattr(self.auth_adapter, "adapter_version", "") == "real-v1":
            raise GatewayError(501, "direct_bearer_disabled", "real-v1 uses Codex App Server instead of direct bearer forwarding")
        if not self.upstream_url:
            raise GatewayError(503, "upstream_not_configured", "Set CODEX_ROUTER_UPSTREAM_URL before sending requests")
        _validate_upstream_url(self.upstream_url)
        session, fingerprint = self._authenticate()
        self.ensure_session_current(fingerprint)

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        url = self.upstream_url + (path if path.startswith("/") else "/" + path)
        request = Request(url, data=data, method=method.upper())
        request.add_header("Authorization", "Bearer " + session.access_token)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            if hasattr(self.opener, "open"):
                return self.opener.open(request, timeout=self.timeout)
            return self.opener(request, timeout=self.timeout)
        except GatewayError:
            raise
        except HTTPError as exc:
            if exc.code == 401:
                raise GatewayError(401, "auth_expired", "Codex access token was rejected; run codex login")
            raise GatewayError(exc.code, "upstream_error", "Upstream returned an HTTP error")
        except URLError:
            raise GatewayError(502, "upstream_unavailable", "Upstream could not be reached")

    @staticmethod
    def _map_app_server_error(error):
        return GatewayError(error.status, error.code, error.message)

    @staticmethod
    def _map_model_catalog_error(error):
        return GatewayError(error.status, error.code, error.message)

    def _model_candidates(self, model):
        if self.model_catalog is not None:
            return self.model_catalog.resolve_candidates(model, self.model_fallbacks)
        return [model]

    def open_chat(self, payload):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1":
            return self.open_upstream("POST", "/chat/completions", payload)
        if self.app_server is None:
            raise GatewayError(503, "app_server_unavailable", "Codex App Server is not configured")
        usage_handle = None
        try:
            candidates = self._model_candidates(payload.get("model"))
            response = None
            selected_model = payload.get("model")
            for index, candidate in enumerate(candidates):
                request_payload = dict(payload)
                if candidate:
                    request_payload["model"] = candidate
                else:
                    request_payload.pop("model", None)
                try:
                    response = self.app_server.start_chat(request_payload)
                    selected_model = candidate
                    payload = request_payload
                    break
                except AppServerError as error:
                    if error.code != "model_unavailable" or index + 1 >= len(candidates):
                        raise
            if response is None:
                raise AppServerError(503, "model_unavailable", "No configured Codex model is available")
            if self.usage_tracker is not None:
                usage_handle = self.usage_tracker.begin(selected_model or "codex")
                setter = getattr(response, "set_usage_callback", None)
                if setter:
                    setter(usage_handle.record_token_usage)
            if not payload.get("stream") and hasattr(response, "iter_bytes"):
                try:
                    body = b"".join(response.iter_bytes())
                    if usage_handle is not None:
                        usage_handle.complete("completed")
                    return _MemoryResponse(body)
                except Exception:
                    if usage_handle is not None:
                        usage_handle.complete("failed")
                    raise
                finally:
                    response.close()
            if usage_handle is not None:
                return _TrackedResponse(response, usage_handle)
            return response
        except AppServerError as error:
            if usage_handle is not None:
                usage_handle.complete("failed")
            raise self._map_app_server_error(error)
        except ModelCatalogError as error:
            raise self._map_model_catalog_error(error)

    @staticmethod
    def _responses_messages(payload):
        if not isinstance(payload, dict):
            raise GatewayError(400, "invalid_payload", "Request body must be a JSON object")
        allowed = {"model", "input", "instructions", "stream"}
        if set(payload).difference(allowed):
            raise GatewayError(400, "unsupported_request_options", "Responses options are not supported by the Codex text adapter")
        if "stream" in payload and not isinstance(payload["stream"], bool):
            raise GatewayError(400, "invalid_stream", "stream must be boolean")
        messages = []
        instructions = payload.get("instructions")
        if instructions is not None:
            if not isinstance(instructions, str) or not instructions:
                raise GatewayError(400, "invalid_instructions", "instructions must be text")
            messages.append({"role": "system", "content": instructions})
        value = payload.get("input")
        if isinstance(value, str) and value:
            messages.append({"role": "user", "content": value})
            return messages
        if not isinstance(value, list) or not value:
            raise GatewayError(400, "invalid_input", "input must be a non-empty text value or message array")
        for item in value:
            if not isinstance(item, dict):
                raise GatewayError(400, "unsupported_input", "Responses input must contain text message objects")
            item_type = item.get("type", "message")
            role = item.get("role")
            content = item.get("content")
            if item_type != "message" or role not in ("system", "user", "assistant"):
                raise GatewayError(400, "unsupported_input", "Only text message input is supported")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict) or part.get("type") not in ("input_text", "output_text", "text") or not isinstance(part.get("text"), str):
                        raise GatewayError(400, "unsupported_input", "Only text message input is supported")
                    parts.append(part["text"])
                text = "\n".join(parts)
            else:
                raise GatewayError(400, "unsupported_input", "Only text message input is supported")
            messages.append({"role": role, "content": text})
        if not messages:
            raise GatewayError(400, "invalid_input", "input must contain a text message")
        return messages

    def open_responses(self, payload):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1":
            raise GatewayError(501, "responses_not_supported", "Responses API is only available through Codex App Server")
        if self.app_server is None:
            raise GatewayError(503, "app_server_unavailable", "Codex App Server is not configured")
        messages = self._responses_messages(payload)
        try:
            candidates = self._model_candidates(payload.get("model"))
            response = None
            model = payload.get("model")
            for index, candidate in enumerate(candidates):
                chat_payload = {"messages": messages, "stream": bool(payload.get("stream", False))}
                if candidate:
                    chat_payload["model"] = candidate
                try:
                    response = self.app_server.start_chat(chat_payload)
                    model = candidate
                    break
                except AppServerError as error:
                    if error.code != "model_unavailable" or index + 1 >= len(candidates):
                        raise
            if response is None:
                raise AppServerError(503, "model_unavailable", "No configured Codex model is available")
            translated = _ResponsesResponse(response, model, bool(payload.get("stream", False)))
            if self.usage_tracker is not None:
                usage_handle = self.usage_tracker.begin(model or "codex")
                translated.set_usage_callback(usage_handle.record_token_usage)
                return _TrackedResponse(translated, usage_handle)
            return translated
        except AppServerError as error:
            raise self._map_app_server_error(error)
        except ModelCatalogError as error:
            raise self._map_model_catalog_error(error)

    def open_models(self):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1":
            return self.open_upstream("GET", "/models")
        if self.app_server is None:
            raise GatewayError(503, "app_server_unavailable", "Codex App Server is not configured")
        try:
            if self.model_catalog is not None:
                models = self.model_catalog.list_models()
                data = []
                for item in models:
                    data.append({
                        "id": item["id"],
                        "object": "model",
                        "created": 0,
                        "owned_by": item["owned_by"],
                    })
                headers = {"X-Codex-Router-Catalog": "stale"} if self.model_catalog.stale else None
                body = json.dumps({"object": "list", "data": data}, separators=(",", ":")).encode("utf-8")
                return _MemoryResponse(body, headers=headers)
            return self.app_server.list_models()
        except AppServerError as error:
            raise self._map_app_server_error(error)
        except ModelCatalogError as error:
            raise self._map_model_catalog_error(error)

    def dashboard_models(self):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1" or self.model_catalog is None:
            return []
        try:
            return self.model_catalog.list_models()
        except AppServerError as error:
            raise self._map_app_server_error(error)
        except ModelCatalogError as error:
            raise self._map_model_catalog_error(error)
