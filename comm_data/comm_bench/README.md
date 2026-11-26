# 라즈베리파이 텍스트 통신 벤치마크

같은 공유기에 연결된 Raspberry Pi OS Debian 13(trixie) 두 대에서 TCP, UDP, HTTP, MQTT의 UTF-8 텍스트 왕복을 비교한다. 22번 Pi(`192.168.20.22`)가 메시지를 보내고, 49번 Pi(`192.168.20.49`)가 받은 바이트를 그대로 돌려준다. 22번의 `time.perf_counter()`로 왕복 시간(RTT)을 재므로 두 Pi의 시계를 맞출 필요가 없다. Python 3 표준 라이브러리와 두 Pi에 설치된 `paho-mqtt`만 사용한다.

| 방식 | 연결과 에코 경로 | 결과에서 볼 점 |
| --- | --- | --- |
| `tcp` | 5001번 포트, 연결 재사용, 4바이트 길이 헤더, 양쪽 `TCP_NODELAY` | 오버헤드가 작고 스트림이 재전송을 담당해 빠른 RTT와 낮은 손실을 기대할 수 있다. |
| `udp` | 5002번 포트, 메시지당 데이터그램 하나 | TCP와 함께 빠른 RTT를 기대할 수 있다. 패킷이 유실되면 타임아웃이 손실로 잡힌다. 8KB는 일반적인 MTU에서 IP 단편화의 영향을 받을 수 있다. |
| `http-keepalive` | 5003번 포트, HTTP/1.1 `POST /echo`, TCP 연결 재사용 | HTTP 헤더와 서버의 파싱 비용이 포함된다. |
| `http-new` | 같은 HTTP 엔드포인트, 요청마다 `Connection: close`와 새 TCP 연결 | 요청마다 TCP 핸드셰이크와 서버의 연결 처리 비용이 더해진다. |
| `mqtt-qos0`, `mqtt-qos1` | 1883번 Mosquitto 브로커 경유, `bench/ping` → 에코 프로세스 → `bench/pong` | 브로커 경유 홉이 추가된다. QoS 0은 발행 확인 응답이 없고, QoS 1은 확인 응답과 재전송 가능성이 있어 지연과 처리량에 영향을 줄 수 있다. 양방향에 선택한 QoS를 적용한다. |

## 복사 및 실행

노트북 PowerShell에서 저장소의 `comm_data` 폴더로 이동한 뒤 다음을 실행한다. 49번 Pi에서 익명 연결을 허용하는 Mosquitto가 1883번 포트에 이미 실행 중이어야 한다.

```powershell
cd <저장소 경로>\comm_data
scp .\comm_bench\bench_server.py linux@192.168.20.49:~/
scp .\comm_bench\bench_client.py linux@192.168.20.22:~/
```

**MQTT를 공정하게 재려면 브로커에도 TCP_NODELAY를 켠다 (처음 한 번).** Mosquitto는 기본값이 꺼져 있어서, 작은 메시지가 Nagle 알고리즘 때문에 수십 ms씩 묶이고 MQTT(특히 QoS 1)만 불리하게 나온다. 스크립트 쪽 MQTT 클라이언트는 이미 TCP_NODELAY를 켠다.

```powershell
ssh -t linux@192.168.20.49 "echo 'set_tcp_nodelay true' | sudo tee -a /etc/mosquitto/conf.d/lan.conf && sudo systemctl restart mosquitto"
```

첫 번째 PowerShell 창에서 서버를 실행하고 `Echo ready`와 MQTT 토픽 안내가 표시될 때까지 기다린다.

```powershell
ssh -t linux@192.168.20.49 "python3 ~/bench_server.py"
```

두 번째 PowerShell 창에서 클라이언트를 실행한다. 첫 명령은 전체 측정이고, 두 번째는 방법과 크기를 선택하는 짧은 실행 예다.

```powershell
ssh -t linux@192.168.20.22 "python3 ~/bench_client.py"
ssh -t linux@192.168.20.22 "python3 ~/bench_client.py --methods tcp,udp,http-keepalive,http-new --sizes 16B,256B,1KB,8KB --count 50 --duration 1 --warmup 20 --timeout 1"
```

기본 설정은 6가지 방식과 4가지 페이로드(16, 256, 1024, 8192바이트)를 명령에 나열된 순서대로 실행한다. 조합마다 예열 20회, RTT 측정 500회, 처리량 측정 5초, 응답 타임아웃 1초를 사용한다. `--methods`와 `--sizes`는 쉼표 또는 공백으로 구분할 수 있다. 클라이언트의 `--host`와 `--broker` 기본값은 각각 `192.168.20.49`다. 서버는 기본적으로 `0.0.0.0`에 바인딩하고 `localhost`의 브로커를 사용한다. MQTT 없이 실행하려면 서버에 `--no-mqtt`를 추가하고 클라이언트의 `--methods`에서 MQTT를 제외한다. 양쪽 스크립트에서 `--broker`와 `--broker-port`로 브로커 주소와 포트를 바꿀 수 있다.

측정이 끝나면 첫 번째 창에서 `Ctrl+C`로 서버를 종료한다. CSV는 클라이언트 스크립트 옆 `results` 폴더에 저장되므로, 위와 같이 홈 디렉터리에 복사했다면 다음과 같이 가져온다.

```powershell
New-Item -ItemType Directory -Force .\comm_bench\results | Out-Null
scp 'linux@192.168.20.22:~/results/bench_*.csv' .\comm_bench\results\
```

## 측정과 결과 해석

- 모든 방식이 같은 크기의 UTF-8 페이로드를 쓴다. 16바이트 식별자에는 실행 식별값과 시퀀스 번호가 들어가며 명시한 크기에 포함된다. TCP 길이 헤더나 HTTP, MQTT의 프로토콜 헤더는 페이로드 크기에서 제외한다. UDP와 MQTT는 지난 요청의 응답이나 중복 응답을 현재 요청의 성공으로 세지 않는다. 모든 방식에서 응답 바이트가 요청과 일치해야 성공으로 센다.
- `Avg ms`, `Med ms`, `p95 ms`, `p99 ms`, `Max ms`는 성공한 왕복만으로 계산한다. p95와 p99는 정렬된 표본을 선형 보간한 값으로, 각각 대략 95%, 99%의 성공 응답이 이 시간 이내에 도착했음을 뜻한다. 성공 표본이 없으면 RTT 통계는 비워 둔다. p99는 표본 수가 적을 때 소수의 느린 응답에 민감하다.
- `Msg/s`는 설정한 시간 안에 응답 검증까지 끝낸 메시지 수를 설정 시간(초)으로 나눈 값이다. **모든 방식은 응답을 받거나 타임아웃이 발생한 뒤 다음 메시지를 보내는 동기 방식**으로 처리량을 잰다. 연결을 재사용하는 방식의 초기 연결 및 MQTT 구독 설정은 측정 전에 끝낸다. `http-new`는 매번 연결을 맺는 시간도 포함한다. 이 처리량은 한 번에 한 요청을 보내는 애플리케이션의 왕복 처리 속도다.
- `RTT loss%`와 `Rate loss%`는 각 구간에서 발송한 요청 중 타임아웃 안에 응답을 확인하지 못한 비율이다. 처리량 구간 종료 직전에 발송한 요청은 타임아웃까지 기다리므로 손실률과 수신 건수에는 반영된다. 구간 끝 이후 도착한 응답은 `Msg/s`의 분자에서 제외한다. CSV에는 각 구간의 발송·수신 건수, 처리량 구간 안에 완료한 건수, 시간 설정, 오류를 함께 기록한다. 연결 실패나 페이로드 불일치는 `Error`로 표시한다.
- 카메라 스트리밍, 대용량 전송 등 다른 부하를 멈추고 같은 연결 조건으로 비교한다. Wi-Fi의 신호 세기, 채널 혼잡, 재전송은 RTT와 손실에 영향을 줄 수 있다. 방법과 크기별 측정을 여러 번 반복하고, 시간에 따른 네트워크 부하 변화가 의심되면 `--methods` 순서를 바꿔 반복한다. 브로커와 에코 서버가 같은 49번 Pi에 있으므로 MQTT의 추가 브로커 경로 일부는 Pi 내부를 지난다.
