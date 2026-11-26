#!/usr/bin/env python3
"""
49번 Pi (RGB 카메라 + 통합)
22번이 보낸 NoIR 프레임을 받아, 촬영 시각이 가장 가까운 RGB 프레임과 짝지어 겹친다.

  python3 fusion_receiver.py               가짜 RGB 영상 (카메라 오기 전)
  python3 fusion_receiver.py --source pi   실제 RGB 카메라 (picamera2)
  --show                                   창으로 보기 (RDP 화면 안 터미널에서 실행할 때)

결과: ~/fusion_out/latest.jpg  ( RGB | IR | 통합 ) 를 1초마다 덮어쓴다.
실시간 보기: 노트북 브라우저에서 http://192.168.20.49:8080  (--http-port 0 이면 끔)
"""
import argparse
import collections
import http.server
import math
import os
import socket
import struct
import sys
import threading
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
TOPIC = "cam/ir"
HEADER = struct.Struct("!dI")


def object_position(t, w, h):
    """가짜 영상 속 움직이는 물체 위치. ir_sender.py 와 같은 식이어야 한다."""
    x = w / 2 + w * 0.35 * math.cos(t * 0.8)
    y = h / 2 + h * 0.30 * math.sin(t * 1.6)
    return int(x), int(y)


def fake_rgb_frames(w, h, fps):
    """그라데이션 배경 + 고정된 빨간 사각형 + 움직이는 노란 공."""
    bg = np.zeros((h, w, 3), np.uint8)
    bg[..., 0] = np.linspace(40, 200, w, dtype=np.uint8)[None, :]
    bg[..., 1] = np.linspace(60, 160, h, dtype=np.uint8)[:, None]
    bg[..., 2] = 90
    period = 1.0 / fps
    while True:
        t = time.time()
        img = bg.copy()
        cv2.rectangle(img, (20, 20), (w // 4, h // 4), (40, 40, 200), -1)
        cv2.circle(img, object_position(t, w, h), h // 8, (0, 220, 255), -1)
        yield t, img
        time.sleep(max(0.0, period - (time.time() - t)))


def pi_rgb_frames(w, h, fps):
    """실제 RGB 카메라. 카메라가 오면 --source pi 로 실행."""
    from picamera2 import Picamera2

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (w, h), "format": "RGB888"},  # 메모리 순서는 BGR -> OpenCV 와 같음
        controls={"FrameRate": fps},
    ))
    cam.start()
    time.sleep(1)
    while True:
        frame = cam.capture_array()
        yield time.time(), frame


class IrBuffer:
    """MQTT 로 받은 최근 IR 프레임 보관 (MQTT 스레드에서 쓰고, 메인 루프에서 읽음)."""

    def __init__(self, maxlen=30):
        self.lock = threading.Lock()
        self.frames = collections.deque(maxlen=maxlen)
        self.received = 0
        self.delay_sum = 0.0

    def on_message(self, client, userdata, msg):
        if len(msg.payload) <= HEADER.size:
            return
        t, seq = HEADER.unpack_from(msg.payload)
        gray = cv2.imdecode(np.frombuffer(msg.payload, np.uint8, offset=HEADER.size),
                            cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return
        with self.lock:
            self.frames.append((t, seq, gray))
            self.received += 1
            self.delay_sum += time.time() - t

    def closest(self, t):
        with self.lock:
            if not self.frames:
                return None
            return min(self.frames, key=lambda f: abs(f[0] - t))

    def pop_stats(self):
        with self.lock:
            n, d = self.received, self.delay_sum
            self.received, self.delay_sum = 0, 0.0
        return n, (d / n if n else 0.0)


class LatestFrame:
    """브라우저로 보낼 최신 JPEG 한 장."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpg = None
        self.seq = 0

    def put(self, jpg):
        with self.cond:
            self.jpg = jpg
            self.seq += 1
            self.cond.notify_all()

    def wait_next(self, last_seq, timeout=2.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout=timeout)
            return self.seq, self.jpg


PAGE = b"""<!doctype html><meta charset="utf-8"><title>fusion</title>
<body style="margin:0;background:#111;color:#ccc;font-family:sans-serif">
<p style="margin:8px">RGB (49) | IR (22) | FUSED</p>
<img src="/stream" style="width:100%;max-width:1440px;display:block">
</body>"""


def start_http(port, latest):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(PAGE)
            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                seq = -1
                try:
                    while True:
                        seq, jpg = latest.wait_next(seq)
                        if jpg is None:
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            else:
                self.send_error(404)

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def fuse(rgb, ir_gray, H, alpha):
    h, w = rgb.shape[:2]
    ir = cv2.resize(ir_gray, (w, h))
    if H is not None:  # 카메라가 온 뒤 위치 보정(호모그래피)을 구하면 적용
        ir = cv2.warpPerspective(ir, H, (w, h))
    ir_color = cv2.applyColorMap(ir, cv2.COLORMAP_INFERNO)
    return ir, cv2.addWeighted(rgb, 1 - alpha, ir_color, alpha, 0)


def label(img, text, y=24, color=(255, 255, 255)):
    cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)


def make_client(prefix):
    # 브로커는 같은 ID 가 접속하면 먼저 있던 쪽을 끊는다 -> 기기·프로세스마다 다른 ID 사용
    client_id = f"{prefix}-{socket.gethostname()}-{os.getpid()}"
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["fake", "pi"], default="fake")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--tolerance", type=float, default=0.15, help="짝지을 최대 시각 차이(초)")
    ap.add_argument("--alpha", type=float, default=0.4, help="IR 겹침 비율 0~1")
    ap.add_argument("--homography", help="위치 보정 행렬 .npy (나중에)")
    ap.add_argument("--out", default=os.path.expanduser("~/fusion_out"))
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--http-port", type=int, default=8080, help="브라우저 실시간 보기 포트 (0=끔)")
    args = ap.parse_args()

    latest = LatestFrame()
    if args.http_port:
        start_http(args.http_port, latest)
        print(f"[fusion] 브라우저로 보기: http://<이 Pi IP>:{args.http_port}")

    H = np.load(args.homography) if args.homography else None
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "latest.jpg")
    tmp_path = os.path.join(args.out, "latest.tmp.jpg")

    buf = IrBuffer()

    def on_connect(client, userdata, flags, rc, properties=None):
        client.subscribe(TOPIC, qos=0)
        print(f"[fusion] 브로커 연결됨, {TOPIC} 구독")

    client = make_client("fusion")
    client.on_connect = on_connect
    client.on_message = buf.on_message
    try:
        client.connect(args.broker, PORT, keepalive=30)
    except OSError as e:
        sys.exit(f"[fusion] 브로커 {args.broker}:{PORT} 연결 실패: {e}")
    client.loop_start()
    print(f"[fusion] 소스 {args.source} / {args.width}x{args.height} @ {args.fps:g}fps / "
          f"결과 {out_path}  (Ctrl+C 로 종료)")

    gen = fake_rgb_frames if args.source == "fake" else pi_rgb_frames
    rgb_n = matched = 0
    dt_sum = 0.0
    last_report = last_save = time.time()
    try:
        for t, rgb in gen(args.width, args.height, args.fps):
            rgb_n += 1
            m = buf.closest(t)
            if m is not None and abs(m[0] - t) <= args.tolerance:
                dt = m[0] - t
                ir, fused = fuse(rgb, m[2], H, args.alpha)
                matched += 1
                dt_sum += abs(dt)
                ir_panel = cv2.cvtColor(ir, cv2.COLOR_GRAY2BGR)
                label(fused, f"dt {dt * 1000:+.0f} ms")
            else:
                ir_panel = np.zeros_like(rgb)
                label(ir_panel, "NO IR", color=(0, 0, 255))
                fused = rgb.copy()
                label(fused, "NO IR MATCH", color=(0, 0, 255))

            rgb_panel = rgb.copy()
            label(rgb_panel, "RGB (49)")
            label(ir_panel, "IR (22)", y=48)
            label(fused, "FUSED", y=48)
            half = (args.width // 2, args.height // 2)
            panel = cv2.hconcat([cv2.resize(p, half) for p in (rgb_panel, ir_panel, fused)])

            if args.http_port:
                ok, jpg = cv2.imencode(".jpg", panel, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    latest.put(jpg.tobytes())

            now = time.time()
            if now - last_save >= 1:
                cv2.imwrite(tmp_path, panel)
                os.replace(tmp_path, out_path)
                last_save = now
            if args.show:
                cv2.imshow("fusion", panel)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            if now - last_report >= 5:
                el = now - last_report
                ir_n, delay = buf.pop_stats()
                rate = matched / rgb_n * 100 if rgb_n else 0
                avg_dt = dt_sum / matched * 1000 if matched else 0
                print(f"[fusion] RGB {rgb_n / el:.1f} fps | IR 수신 {ir_n / el:.1f} fps | "
                      f"짝 성공 {rate:.0f}% | 평균 |dt| {avg_dt:.0f} ms | IR 도착 지연 {delay * 1000:.0f} ms")
                if ir_n == 0:
                    print("[fusion]   IR 프레임이 안 온다 -> 22번 ir_sender.py 가 실행 중인지 확인")
                rgb_n = matched = 0
                dt_sum = 0.0
                last_report = now
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        if args.show:
            cv2.destroyAllWindows()
        print("[fusion] 종료")


if __name__ == "__main__":
    main()
