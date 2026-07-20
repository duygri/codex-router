"""Command-line entry point for the local Codex router."""

import argparse
import json
import os

from .auth import AuthAdapter
from .config import RouterConfig
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
    subparsers.add_parser("status", help="print safe local status")
    subparsers.add_parser("reset", help="clear router metadata without touching Codex auth")
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
        host = args.host or config.bind_host
        port = args.port or config.port
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
