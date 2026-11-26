"""Benchmark synchronous UTF-8 echo round trips over TCP, UDP, HTTP and MQTT."""

import argparse
import csv
import http.client
import math
import os
import queue
import re
import socket
import statistics
import struct
import threading
import time
from contextlib import ExitStack
from datetime import datetime
from itertools import count
from pathlib import Path


DEFAULT_HOST = "192.168.20.49"
TCP_PORT = 5001
UDP_PORT = 5002
HTTP_PORT = 5003
TAG_SIZE = 16
MAX_PAYLOAD = 65507
PING_TOPIC = "bench/ping"
PONG_TOPIC = "bench/pong"
LENGTH = struct.Struct("!I")
METHODS = ("tcp", "udp", "http-keepalive", "http-new", "mqtt-qos0", "mqtt-qos1")
SIZES = (16, 256, 1024, 8192)


def remaining(deadline):
    seconds = deadline - time.perf_counter()
    if seconds <= 0:
        raise TimeoutError("Echo deadline passed")
    return seconds


def read_exact(sock, size, deadline):
    data = bytearray()
    while len(data) < size:
        sock.settimeout(remaining(deadline))
        part = sock.recv(size - len(data))
        if not part:
            raise ConnectionError("TCP peer closed before the full echo arrived")
        data.extend(part)
    return data


class TcpEcho:
    def __init__(self, host, timeout):
        self.host = host
        self.sock = None
        self.connect(timeout)

    def connect(self, timeout):
        self.sock = socket.create_connection((self.host, TCP_PORT), timeout)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            self.close()
            raise

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def exchange(self, payload, deadline):
        try:
            if self.sock is None:
                self.connect(remaining(deadline))
            self.sock.settimeout(remaining(deadline))
            self.sock.sendall(LENGTH.pack(len(payload)) + payload)
            size, = LENGTH.unpack(read_exact(self.sock, LENGTH.size, deadline))
            if size != len(payload):
                raise ValueError(f"TCP echo length {size}, expected {len(payload)}")
            return read_exact(self.sock, size, deadline)
        except TimeoutError:
            self.close()  # The next probe needs a fresh TCP stream after a partial frame.
            raise


def udp_exchange(sock, payload, deadline):
    tag = payload[:TAG_SIZE]
    sock.settimeout(remaining(deadline))
    sock.send(payload)
    while True:
        sock.settimeout(remaining(deadline))
        reply = sock.recv(MAX_PAYLOAD)
        if reply[:TAG_SIZE] == tag:
            return reply


def http_exchange(connection, payload, deadline, fresh):
    try:
        connection.timeout = remaining(deadline)
        if connection.sock is not None:
            connection.sock.settimeout(connection.timeout)
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if fresh:
            headers["Connection"] = "close"
        connection.request("POST", "/echo", body=payload, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(remaining(deadline))
        with connection.getresponse() as response:
            if response.status != 200:
                raise ValueError(f"HTTP response status {response.status}")
            if response.length != len(payload):
                raise ValueError(f"HTTP echo length {response.length}, expected {len(payload)}")
            return response.read()
    except TimeoutError:
        connection.close()
        raise
    finally:
        if fresh:
            connection.close()


def make_client(mqtt, prefix):
    client_id = f"{prefix}-{socket.gethostname()}-{os.getpid()}"
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=client_id)
    client.on_socket_open = _set_nodelay
    return client


def _set_nodelay(client, userdata, sock):
    # paho-mqtt 는 TCP_NODELAY 를 켜지 않는다. 켜지 않으면 작은 메시지가 Nagle 때문에
    # 수십~100 ms 묶여서 MQTT 만 불리해진다 (tcp 방식과 같은 조건으로 맞춤).
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass


def mqtt_exchange_function(args, qos, stack):
    import paho.mqtt.client as mqtt

    client = make_client(mqtt, f"bench-client-qos{qos}")
    subscribed = threading.Event()
    replies = queue.Queue()
    errors = []

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            result, _ = client.subscribe(PONG_TOPIC, qos=qos)
            if result == mqtt.MQTT_ERR_SUCCESS:
                return
            errors.append(f"MQTT subscribe failed: {result}")
        else:
            errors.append(f"MQTT connect rejected: {rc}")
        subscribed.set()

    def on_subscribe(client, userdata, mid, granted_qos, properties=None):
        if [getattr(grant, "value", grant) for grant in granted_qos] != [qos]:
            errors.append(f"MQTT requires a QoS {qos} subscription: {granted_qos}")
        subscribed.set()

    def on_message(client, userdata, message):
        if not message.retain:
            replies.put(message.payload)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    result = client.connect(args.broker, args.broker_port)
    if result != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"MQTT connect failed: {result}")
    client.loop_start()
    stack.callback(client.loop_stop)
    stack.callback(client.disconnect)
    if not subscribed.wait(max(5.0, args.timeout)):
        raise TimeoutError(f"MQTT subscription timed out at {args.broker}:{args.broker_port}")
    if errors:
        raise RuntimeError(errors[0])

    def exchange(payload, deadline):
        info = client.publish(PING_TOPIC, payload, qos=qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed: {info.rc}")
        tag = payload[:TAG_SIZE]
        while True:
            try:
                reply = replies.get(timeout=remaining(deadline))
            except queue.Empty:
                raise TimeoutError("MQTT echo timed out") from None
            if reply[:TAG_SIZE] == tag:
                return reply

    return exchange


def open_exchange(method, args, stack):
    if method == "tcp":
        connection = TcpEcho(args.host, args.timeout)
        stack.callback(connection.close)
        return connection.exchange
    if method == "udp":
        sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        sock.connect((args.host, UDP_PORT))
        return lambda payload, deadline: udp_exchange(sock, payload, deadline)
    if method.startswith("http-"):
        connection = http.client.HTTPConnection(args.host, HTTP_PORT, timeout=args.timeout)
        stack.callback(connection.close)
        fresh = method == "http-new"
        if not fresh:
            connection.connect()
        return lambda payload, deadline: http_exchange(connection, payload, deadline, fresh)
    return mqtt_exchange_function(args, int(method[-1]), stack)


def payloads(size):
    run_id = os.urandom(4).hex()
    # Repeat a three-byte UTF-8 character and pad with ASCII to reach the exact byte count.
    repeats, padding = divmod(size - TAG_SIZE, 3)
    body = ("\uac00" * repeats + "x" * padding).encode("utf-8")
    for sequence in count():
        yield f"{run_id}{sequence:08x}".encode("ascii") + body


def probe(exchange, payload, timeout):
    start = time.perf_counter()
    deadline = start + timeout
    try:
        reply = exchange(payload, deadline)
    except TimeoutError:
        return None, None
    if reply != payload:
        raise ValueError("Echo payload differs from request")
    finish = time.perf_counter()
    if finish > deadline:
        return None, None
    return finish - start, finish


def percentile(sorted_values, fraction):
    rank = (len(sorted_values) - 1) * fraction
    lower = int(rank)
    upper = math.ceil(rank)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def measure(method, size, args, row):
    messages = payloads(size)
    with ExitStack() as stack:
        exchange = open_exchange(method, args, stack)
        for _ in range(args.warmup):
            probe(exchange, next(messages), args.timeout)

        rtts = []
        for _ in range(args.count):
            elapsed, _ = probe(exchange, next(messages), args.timeout)
            if elapsed is not None:
                rtts.append(elapsed * 1000)
        row.update(rtt_sent=args.count, rtt_received=len(rtts), rtt_loss_pct=100 * (args.count - len(rtts)) / args.count)
        if rtts:
            rtts.sort()
            row.update(
                avg_ms=statistics.mean(rtts), median_ms=statistics.median(rtts),
                p95_ms=percentile(rtts, 0.95), p99_ms=percentile(rtts, 0.99), max_ms=rtts[-1],
            )

        sent = received = in_window = 0
        end = time.perf_counter() + args.duration
        while time.perf_counter() < end:
            sent += 1
            _, finish = probe(exchange, next(messages), args.timeout)
            if finish is not None:
                received += 1
                if finish <= end:
                    in_window += 1
        row.update(
            throughput_sent=sent, throughput_received=received, throughput_in_window=in_window,
            throughput_msg_s=in_window / args.duration,
            throughput_loss_pct=100 * (sent - received) / sent if sent else None,
        )


CSV_FIELDS = (
    "method", "size_bytes", "warmup", "timeout_s", "duration_s", "rtt_sent", "rtt_received",
    "rtt_loss_pct", "avg_ms", "median_ms", "p95_ms", "p99_ms", "max_ms", "throughput_sent",
    "throughput_received", "throughput_in_window", "throughput_msg_s", "throughput_loss_pct", "error",
)


def show_result(row):
    def metric(key, precision):
        value = row.get(key)
        return "-" if value is None else f"{value:.{precision}f}"

    print(
        f"{row['method']:<14} {row['size_bytes']:>6} "
        + " ".join(f"{metric(key, 3):>9}" for key in ("avg_ms", "median_ms", "p95_ms", "p99_ms", "max_ms"))
        + f" {metric('rtt_loss_pct', 2):>9} {metric('throughput_msg_s', 1):>10}"
        + f" {metric('throughput_loss_pct', 2):>10}  {row.get('error', '')}",
        flush=True,
    )


def parse_size(token):
    match = re.fullmatch(r"([0-9]+)(B|K|KB|KIB)?", token.upper())
    if not match:
        raise ValueError(f"Invalid payload size: {token}")
    amount, unit = match.groups()
    size = int(amount) * (1024 if unit in ("K", "KB", "KIB") else 1)
    if not TAG_SIZE <= size <= MAX_PAYLOAD:
        raise ValueError(f"Payload size must be {TAG_SIZE}..{MAX_PAYLOAD} bytes: {token}")
    return size


def split_list(values):
    return [part.strip() for value in values for part in value.split(",")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, help="TCP/UDP/HTTP server hostname")
    parser.add_argument("--broker", default=DEFAULT_HOST, help="MQTT broker hostname")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--methods", nargs="+", metavar="METHOD", default=METHODS, help=", ".join(METHODS))
    parser.add_argument("--sizes", nargs="+", metavar="SIZE", default=[str(size) for size in SIZES], help="Default: 16B, 256B, 1KB, 8KB")
    parser.add_argument("--count", type=int, default=500, help="RTT attempts for each method and size")
    parser.add_argument("--duration", type=float, default=5.0, help="Throughput window in seconds")
    parser.add_argument("--warmup", type=int, default=20, help="Unmeasured attempts for each method and size")
    parser.add_argument("--timeout", type=float, default=1.0, help="Echo timeout in seconds")
    args = parser.parse_args()

    methods = split_list(args.methods)
    unknown_methods = [method for method in methods if method not in METHODS]
    if unknown_methods:
        parser.error(f"Unknown methods: {', '.join(map(repr, unknown_methods))}")
    try:
        sizes = [parse_size(token) for token in split_list(args.sizes)]
    except ValueError as exc:
        parser.error(str(exc))
    if args.count <= 0 or args.warmup < 0:
        parser.error("--count must be positive and --warmup must be nonnegative")
    if any(not math.isfinite(value) or value <= 0 for value in (args.duration, args.timeout)):
        parser.error("--duration and --timeout must be positive finite seconds")

    directory = Path(__file__).resolve().parent / "results"
    directory.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"bench_{timestamp}.csv"
    print(
        f"{'Method':<14} {'Bytes':>6} {'Avg ms':>9} {'Med ms':>9} {'p95 ms':>9} {'p99 ms':>9}"
        f" {'Max ms':>9} {'RTT loss%':>9} {'Msg/s':>10} {'Rate loss%':>10}  Error",
        flush=True,
    )
    had_errors = False
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for method in methods:
            for size in sizes:
                row = dict(method=method, size_bytes=size, warmup=args.warmup, timeout_s=args.timeout, duration_s=args.duration)
                try:
                    measure(method, size, args, row)
                except (ImportError, OSError, RuntimeError, ValueError, http.client.HTTPException) as exc:
                    row["error"] = str(exc) or type(exc).__name__
                    had_errors = True
                writer.writerow(row)
                output.flush()
                show_result(row)
    print(f"CSV: {path}")
    return int(had_errors)


if __name__ == "__main__":
    raise SystemExit(main())
