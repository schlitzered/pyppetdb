import asyncio
import socket
import ssl
import websockets
import argparse
from cryptography import x509
from cryptography.hazmat.backends import default_backend


def get_puppet_ssl_context():
    fqdn = socket.getfqdn()
    base_path = "/etc/puppetlabs/puppet/ssl"

    ca_cert = f"{base_path}/certs/ca.pem"
    client_cert = f"{base_path}/certs/{fqdn}.pem"
    client_key = f"{base_path}/private_keys/{fqdn}.pem"

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    try:
        context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    except Exception as e:
        print(f"Warning: Could not load client certificate/key: {e}")
    return context, client_cert


def get_cert_cn(cert_path):
    try:
        with open(cert_path, "rb") as f:
            cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        common_names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        if common_names:
            return common_names[0].value
    except Exception as e:
        print(f"Error extracting CN from certificate: {e}")
    return None


async def handle_websocket(websocket):
    print("Connected! Entering ping/pong loop...")
    try:
        while True:
            print("Sending ping...")
            await websocket.send("ping")

            print("Waiting for response...")
            response = await websocket.recv()
            print(f"Received from server: {response}")

            if response == "pong":
                print("Ping/Pong successful.")
            else:
                print(f"Unexpected response: {response}")

            print("Sleeping for 10 seconds...")
            await asyncio.sleep(10)
    except websockets.exceptions.ConnectionClosed:
        print("Connection closed by server.")


async def run_client(base_url, insecure=False):
    # Ensure scheme is present
    if not base_url.startswith(("ws://", "wss://")):
        base_url = f"wss://{base_url}"

    print("Loading Puppet SSL certificates...")
    ssl_context, cert_path = get_puppet_ssl_context()

    node_id = get_cert_cn(cert_path)
    if not node_id:
        print(
            "Failed to determine node_id from certificate CN. Using FQDN as fallback."
        )
        node_id = socket.getfqdn()

    print(f"Identified as node: {node_id}")

    # Strip trailing slash and append path with node_id
    url = base_url.rstrip("/") + f"/api/v1/ws/remote_executor/{node_id}"

    while True:
        print(f"Connecting to {url}...")
        try:
            current_ssl_context = None
            if url.startswith("wss://"):
                current_ssl_context = ssl_context
                if insecure:
                    current_ssl_context.check_hostname = False
                    current_ssl_context.verify_mode = ssl.CERT_NONE
                print("Using secure WebSocket connection with mTLS")
            else:
                print("Using insecure WebSocket connection")

            async with websockets.connect(
                url, ssl=current_ssl_context, open_timeout=10
            ) as websocket:
                await handle_websocket(websocket)

        except Exception as e:
            print(f"Connection error: {e}")

        print("Retrying in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote Executor PoC Client")
    parser.add_argument("url", help="Base URL or Host (e.g. puppetsrv-1:8000)")
    parser.add_argument(
        "--insecure", action="store_true", help="Skip certificate verification"
    )

    args = parser.parse_args()

    asyncio.run(run_client(args.url, args.insecure))
