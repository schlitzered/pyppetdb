import asyncio
import socket
import ssl
import sys
import websockets
import argparse
import traceback
import random


def get_puppet_ssl_context(insecure=False):
    fqdn = socket.getfqdn()
    base_path = "/etc/puppetlabs/puppet/ssl"

    ca_cert = f"{base_path}/certs/ca.pem"
    client_cert = f"{base_path}/certs/{fqdn}.pem"
    client_key = f"{base_path}/private_keys/{fqdn}.pem"

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    try:
        context.load_cert_chain(certfile=client_cert, keyfile=client_key)
        print(f"mTLS: Loaded client certificate for {fqdn}")
    except Exception as e:
        print(f"Warning: Could not load client certificate/key for mTLS: {e}")

    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def run_chat_client(base_url, insecure=False):
    # Ensure scheme is present
    if not base_url.startswith(("ws://", "wss://")):
        base_url = f"wss://{base_url}"

    # Generate random client id
    client_id = random.randint(1000, 9999)

    # Strip trailing slash and append path
    url = base_url.rstrip("/") + f"/api/v1/ws/chat/{client_id}"

    print(f"Connecting to {url}...")
    try:
        ssl_context = None
        if url.startswith("wss://"):
            ssl_context = get_puppet_ssl_context(insecure)

        async with websockets.connect(url, ssl=ssl_context) as websocket:
            print(
                f"Connected to Chat as client {client_id}! Type message and press Enter."
            )

            async def send_msgs():
                loop = asyncio.get_event_loop()
                while True:
                    msg = await loop.run_in_executor(None, sys.stdin.readline)
                    if not msg:
                        break
                    await websocket.send(msg.strip())

            async def recv_msgs():
                try:
                    while True:
                        response = await websocket.recv()
                        print(f"\n{response}")
                        print("> ", end="", flush=True)
                except websockets.exceptions.ConnectionClosed:
                    print("\nConnection closed by server")

            print("> ", end="", flush=True)
            await asyncio.gather(send_msgs(), recv_msgs())

    except Exception as e:
        print(f"Connection error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chat WebSocket Client (with mTLS)")
    parser.add_argument("url", help="Base URL or Host (e.g. puppetsrv-1:8000)")
    parser.add_argument(
        "--insecure", action="store_true", help="Skip certificate verification"
    )

    args = parser.parse_args()

    asyncio.run(run_chat_client(args.url, args.insecure))
