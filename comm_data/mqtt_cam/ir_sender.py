#!/usr/bin/env python3
"""
22번 Pi (NoIR 카메라) -> MQTT 로 49번에 프레임 전송

  python3 ir_sender.py               가짜 영상 (카메라 오기 전)
  python3 ir_sender.py --source pi   실제 NoIR 카메라 (picamera2)

메시지 형식 (토픽 cam/ir):
  앞 12바이트 = 촬영 시각(float64, 초) + 프레임 번호(uint32), 빅엔디언
  나머지      = 흑백 JPEG
"""
import argparse
import math
import os
import socket
import struct
import sys
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt

BROKER = "192.168.20.49"
PORT = 1883
TOPIC = "cam/ir"
HEADER = struct.Struct("!dI")


def object_position(t, w, h):
    """가짜 영상 속 움직이는 물체 위치. fusion_receiver.py 와 같은 식이어야 한다."""
    x = w / 2 + w * 0.35 * math.cos(t * 0.8)
    y = h / 2 + h * 0.30 * math.sin(t * 1.6)
    return int(x), int(y)


def fake_ir_frames(w, h, fps):
    """어두운 배경에 밝은 물체 하나 (적외선 조명에 비친 물체 흉내)."""
    rng = np.random.default_rng()
    period = 1.0 / fps
    while True:
        t = time.time()
        img = np.full((h, w), 25, np.uint8)
        cv2.circle(img, object_position(t, w, h), h // 8, 220, -1)
        img = cv2.GaussianBlur(img, (0, 0), 3)
        img = cv2.add(img, rng.integers(0, 12, (h, w), dtype=np.uint8))
        yield t, img
        time.sleep(max(0.0, period - (time.time() - t)))


def pi_ir_frames(w, h, fps):
    """실제 NoIR 카메라. 카메라가 오면 --source pi 로 실행."""
    from picamera2 import Picamera2

    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": (w, h), "format": "RGB888"},
        controls={"FrameRate": fps},
    ))
    cam.start()
    time.sleep(1)  # 노출 안정화
    while True:
        frame = cam.capture_array()
        t = time.time()
        yield t, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


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
    ap.add_argument("--quality", type=int, default=70, help="JPEG 품질 1~100")
    args = ap.parse_args()

    client = make_client("ir-sender")
    try:
        client.connect(args.broker, PORT, keepalive=30)
    except OSError as e:
        sys.exit(f"[ir] 브로커 {args.broker}:{PORT} 연결 실패: {e}")
    client.loop_start()
    print(f"[ir] {args.broker}:{PORT} 연결 / 토픽 {TOPIC} / 소스 {args.source} / "
          f"{args.width}x{args.height} @ {args.fps:g}fps  (Ctrl+C 로 종료)")

    gen = fake_ir_frames if args.source == "fake" else pi_ir_frames
    seq = 0
    sent, sent_bytes, last = 0, 0, time.time()
    try:
        for t, gray in gen(args.width, args.height, args.fps):
            ok, jpg = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            if not ok:
                continue
            payload = HEADER.pack(t, seq) + jpg.tobytes()
            client.publish(TOPIC, payload, qos=0)
            seq = (seq + 1) & 0xFFFFFFFF
            sent += 1
            sent_bytes += len(payload)

            now = time.time()
            if now - last >= 5:
                print(f"[ir] {sent / (now - last):.1f} fps 전송, 프레임당 {sent_bytes / sent / 1024:.0f} KB")
                sent, sent_bytes, last = 0, 0, now
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        print("[ir] 종료")


if __name__ == "__main__":
    main()
