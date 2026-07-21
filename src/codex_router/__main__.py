"""Command-line entry point for the local Codex router."""

import argparse
import json
import os
import sys

from .auth import AuthAdapter
from .config import ConfigError, RouterConfig, validate_router_config
from .dashboard import build_status
from .gateway import Gateway
from .server import create_server
from .storage import MetadataStore


def build_parser():
    parser = argparse.ArgumentParser(prog="codex-router")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="start the local gateway")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    start = subparsers.add_parser("start", help="start the local gateway interactively")
    start.add_argument("--host")
    start.add_argument("--port", type=int)
    browser = start.add_mutually_exclusive_group()
    browser.add_argument("--browser", dest="browser", action="store_true")
    browser.add_argument("--no-browser", dest="browser", action="store_false")
    start.set_defaults(browser=None)
    subparsers.add_parser("doctor", help="validate router configuration")
    subparsers.add_parser("status", help="print safe local status")
    subparsers.add_parser("reset", help="clear router metadata without touching Codex auth")
    return parser


def _open_store(config):
    parent = os.path.dirname(config.database_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    return MetadataStore(config.database_path)


def resolve_browser_policy(config, args):
    """Resolve explicit interactive flags over the environment policy."""
    explicit = getattr(args, "browser", None)
    if explicit is True:
        return "always"
    if explicit is False:
        return "never"
    return config.browser_policy


def main():
    return main_with_args(None)


def main_with_args(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    config = RouterConfig.from_env()
    if args.command in ("serve", "start", "doctor"):
        try:
            validate_router_config(config, host=getattr(args, "host", None), port=getattr(args, "port", None))
        except ConfigError:
            print("Router configuration is invalid; fix the configured values before serving.", file=sys.stderr)
            return 2
        if args.command == "doctor":
            print("Router configuration is valid.")
            return 0
        if args.command == "start":
            # Lifecycle/browser behavior is intentionally implemented separately.
            resolve_browser_policy(config, args)
    store = _open_store(config)
    auth = AuthAdapter(config.auth_path, adapter_version=config.adapter_version)
    try:
        if args.command == "status":
            print(json.dumps(build_status(auth, store, config), indent=2))
            return 0
        if args.command == "reset":
            store.reset()
            print("Router metadata reset; Codex CLI session was not changed.")
            return 0
        host = args.host if args.host is not None else config.bind_host
        port = args.port if args.port is not None else config.port
        gateway = Gateway(auth, config.upstream_url)
        server = create_server(gateway, host, port, lambda: build_status(auth, store, config))
        print("Codex Router listening on http://%s:%s" % (host, port))
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
