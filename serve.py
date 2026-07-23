"""Start Vigil bound DUAL-STACK (IPv4 + IPv6) so a phone on the same Wi-Fi can
reach it on normal networks AND on IPv6-only / NAT64 Wi-Fi (via the Mac's
.local name). Plain `uvicorn --host ::` is IPv6-only on some setups, so we build
a dual-stack socket explicitly and hand it to uvicorn. Used by Vigil.command;
the packaged desktop app does the same in desktop.py."""
import os
import socket
import asyncio
import uvicorn
import app


def main():
    port = int(os.environ.get("VIGIL_PORT", "8000") or 8000)
    config = uvicorn.Config(app.app, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    try:
        if socket.has_dualstack_ipv6():
            sock = socket.create_server(("", port), family=socket.AF_INET6, dualstack_ipv6=True)
        else:
            sock = socket.create_server(("0.0.0.0", port))
        asyncio.run(server.serve(sockets=[sock]))
    except Exception as e:
        print("dual-stack bind failed, falling back to IPv4:", e)
        uvicorn.run(app.app, host="0.0.0.0", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
