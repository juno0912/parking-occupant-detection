"""Run the TCP, UDP, HTTP and MQTT text echo endpoints."""

import argparse
import os
import socket
import socketserver
import struct
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TCP_PORT = 5001
UDP_PORT = 5002
HTTP_PORT = 5003
MAX_PAYLOAD = 65507  # Maximum IPv4 UDP payload in bytes.
PING_TOPIC = "bench/ping"
PONG_TOPIC = "bench/pong"
LENGTH = struct.Struct("!I")


class TcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class TcpEcho(socketserver.StreamRequestHandler):
    disable_nagle_algorithm = True

    def handle(self):
        try:
            while header := self.rfile.read(LENGTH.size):
                if len(header) != LENGTH.size:
                    return
                size, = LENGTH.unpack(header)
                if not 0 < size <= MAX_PAYLOAD:
                    return
                payload = self.rfile.read(size)
                if len(payload) != size:
                    return
                self.wfile.write(header + payload)
        except ConnectionError:
            return


class UdpEcho(socketserver.BaseRequestHandler):
    def handle(self):
        payload, sock = self.request
        sock.sendto(payload, self.client_address)


class UdpServer(socketserver.UDPServer):
    max_packet_size = MAX_PAYLOAD


class HttpEcho(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True
    wbufsize = -1  # Flush headers and body together at the end of the request.

    def do_POST(self):
        if self.path != "/echo":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            size = 0
        if not 0 < size <= MAX_PAYLOAD:
            self.send_error(400, "Invalid Content-Length")
            return
        payload = self.rfile.read(size)
        if len(payload) != size:
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(size))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # Avoid console I/O on each measured request.


def make_client(mqtt, prefix):
    client_id = f"{prefix}-{socket.gethostname()}-{os.getpid()}"
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=client_id)
    client.on_socket_open = _set_nodelay
    return client


def _set_nodelay(client, userdata, sock):
    # paho-mqtt 는 TCP_NODELAY 를 켜지 않는다. 켜지 않으면 작은 메시지가 Nagle 때문에 묶인다.
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass


def start_mqtt(broker, port, stack):
    import paho.mqtt.client as mqtt

    client = make_client(mqtt, "bench-server")
    subscribed = threading.Event()
    errors = []

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            result, _ = client.subscribe(PING_TOPIC, qos=1)
            if result == mqtt.MQTT_ERR_SUCCESS:
                return
            errors.append(f"MQTT subscribe failed: {result}")
        else:
            errors.append(f"MQTT connect rejected: {rc}")
        subscribed.set()

    def on_subscribe(client, userdata, mid, granted_qos, properties=None):
        if [getattr(qos, "value", qos) for qos in granted_qos] != [1]:
            errors.append(f"MQTT requires a QoS 1 subscription: {granted_qos}")
        subscribed.set()

    def on_message(client, userdata, message):
        if not message.retain:
            client.publish(PONG_TOPIC, message.payload, qos=message.qos, retain=False)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    result = client.connect(broker, port)
    if result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT connect failed: {result}")
    client.loop_start()
    stack.callback(client.loop_stop)
    stack.callback(client.disconnect)
    if not subscribed.wait(10):
        raise TimeoutError(f"MQTT subscription timed out at {broker}:{port}")
    if errors:
        raise RuntimeError(errors[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="TCP/UDP/HTTP bind address")
    parser.add_argument("--broker", default="localhost", help="MQTT broker hostname")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--no-mqtt", action="store_true", help="Disable the MQTT echo endpoint")
    args = parser.parse_args()

    try:
        with ExitStack() as stack:
            servers = (
                stack.enter_context(TcpServer((args.host, TCP_PORT), TcpEcho)),
                stack.enter_context(UdpServer((args.host, UDP_PORT), UdpEcho)),
                stack.enter_context(ThreadingHTTPServer((args.host, HTTP_PORT), HttpEcho)),
            )
            if not args.no_mqtt:
                start_mqtt(args.broker, args.broker_port, stack)
            for server in servers:
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
                thread.start()
                stack.callback(thread.join)
                stack.callback(server.shutdown)
            print(f"Echo ready on {args.host}: TCP {TCP_PORT}, UDP {UDP_PORT}, HTTP {HTTP_PORT}", flush=True)
            if not args.no_mqtt:
                print(f"MQTT {args.broker}:{args.broker_port}: {PING_TOPIC} -> {PONG_TOPIC}", flush=True)
            threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Server error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
