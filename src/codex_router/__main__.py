"""Command-line entry point for the local Codex router."""

import argparse
import json
import os
import sys

from .auth import AuthAdapter
from .config import ConfigError, RouterConfig, initialize_router_config
from .dashboard import build_dashboard_data, build_status
from .gateway import Gateway
from .server import create_server
from .storage import MetadataStore
from .usage import UsageTracker


def build_parser():
    parser = argparse.ArgumentParser(prog="codex-router")
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="start the local gateway")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    subparsers.add_parser("status", help="print safe local status")
    subparsers.add_parser("reset", help="clear router metadata without touching Codex auth")
    subparsers.add_parser("init", help="create a local router key config")
    key = subparsers.add_parser("key", help="inspect local router key setup")
    key.add_argument("--show", action="store_true", help="print the key explicitly")
    return parser


def _open_store(config):
    parent = os.path.dirname(config.database_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    return MetadataStore(config.database_path)


def main():
    return main_with_args(None)


def main_with_args(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    config = RouterConfig.from_env()
    if args.command == "init":
        try:
            initialize_router_config(config.config_path)
        except ConfigError as error:
            print(str(error), file=sys.stderr)
            return 2
        print("Router config initialized at %s" % config.config_path)
        return 0
    if args.command == "key":
        if not config.router_api_key:
            print("Router key is not configured; run codex-router init first.", file=sys.stderr)
            return 1
        if args.show:
            print(config.router_api_key)
        else:
            print("Router key is configured at %s (use --show only when copying it)." % config.config_path)
        return 0
    if config.config_error and args.command == "serve":
        print("Router configuration is invalid; run codex-router init or fix the configured key file.", file=sys.stderr)
        return 2
    store = _open_store(config)
    auth = AuthAdapter(config.auth_path, adapter_version=config.adapter_version, auth_mode=config.auth_mode)
    try:
        if args.command == "status":
            print(json.dumps(build_status(auth, store, config), indent=2))
            return 0
        if args.command == "reset":
            store.reset()
            print("Router metadata reset; Codex CLI session was not changed.")
            return 0
        host = args.host or config.bind_host
        port = args.port or config.port
        gateway = Gateway(
            auth,
            config.upstream_url,
            app_server_command=config.codex_command,
            app_server_queue_size=config.queue_size,
            app_server_queue_timeout=config.queue_timeout,
            model_fallbacks=config.model_fallbacks,
            usage_tracker=UsageTracker(store),
        )
        server = create_server(
            gateway,
            host,
            port,
            lambda: build_status(auth, store, config),
            router_api_key=config.router_api_key,
            dashboard_data_provider=lambda: build_dashboard_data(auth, store, config, gateway),
        )
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
