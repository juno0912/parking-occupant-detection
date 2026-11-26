# 라즈베리파이 RDP·MQTT·통신 비교 진행 가이드

Nov 25, 2026 · @준호

22번(NoIR 카메라)과 49번(RGB 카메라·통합)이 MQTT로 영상을 주고받는 것까지 확인했고, 다음은 통신 방식 비교 측정이다. 49번이 현재 네트워크에 안 잡혀 막혀 있다.

## 현재 상태

모든 Pi는 Raspberry Pi 4B, Raspberry Pi OS(Debian 13 trixie), 계정 `linux`, 공유기 대역 192.168.20.x 이다. Pi 앞부분 MAC은 모두 `88-A2-9E`(라즈베리파이 제조사)다.

| Pi | IP | MAC | 역할 | 상태 |
| --- | --- | --- | --- | --- |
| 22번 | 192.168.20.22 | 88-A2-9E-98-0E-24 | NoIR 카메라, 송신 | 정상 |
| 49번 | 192.168.20.49 | 88-A2-9E-98-0E-38 | MQTT 브로커, RGB 카메라, 통합 | 네트워크에서 사라짐 (재부팅 후에도 안 잡힘) |
| 23번 | 192.168.20.23 | 88-A2-9E-98-0E-7C | 다른 조원 RDP 대상 | 지금은 꺼져 있음 |
| 37번 | 192.168.20.37 | 88-A2-9E-98-0E-15 | RDP 대상 | 지금은 꺼져 있음 |

- 끝난 것: 22번↔49번 MQTT 통신, 가짜 영상으로 영상 전송·짝 맞추기·겹치기(짝 성공 98\~100%, IR 도착 지연 약 33 ms), 49번 브로커 TCP\_NODELAY 설정
- 남은 것: 49번 복구 또는 교체, 통신 방식 비교 측정, 실제 카메라 연결

## 준비

노트북(Windows) PowerShell에서 프로젝트 폴더로 이동한 뒤 모든 명령을 실행한다.

```powershell
cd <저장소 경로>\comm_data
```

| 파일 | 어디서 실행 | 하는 일 |
| --- | --- | --- |
| `setup_rdp.sh` | 각 Pi | 원격 데스크톱(xrdp) 설치·설정 |
| `mqtt_cam/ir_sender.py` | 22번 | NoIR 프레임을 JPEG로 MQTT 전송 (토픽 `cam/ir`) |
| `mqtt_cam/fusion_receiver.py` | 49번 | IR 수신 + RGB와 시각 기준 짝 맞추기·겹치기, 브라우저 보기(8080) |
| `comm_bench/bench_server.py` | 49번 | TCP 5001·UDP 5002·HTTP 5003 에코 서버 + MQTT 에코 |
| `comm_bench/bench_client.py` | 22번 | 왕복 지연·처리량·손실률 측정, CSV 저장 |
| `comm_bench/README.md` | - | 벤치마크 상세 설명 |

- `ssh`/`scp`는 Pi 비밀번호를 물어보므로 각자 직접 실행한다.
- 처음 접속하면 나오는 "continue connecting" 질문에는 `yes`를 끝까지 입력한다.
- 프로그램을 끌 때는 그 창에서 Ctrl+C를 누른다.

### 조원에게 줄 파일

`ai_pj1` 폴더에서 아래 파일만 폴더 구조 그대로 압축(zip)해서 준다. 이미 묶어 둔 \`ai\_pj1\\조원공유.zip\`을 그대로 줘도 된다. 받은 사람은 압축을 풀고 그 폴더에서 명령을 실행한다.

| 줄 파일 | 필요한 사람 |
| --- | --- |
| `setup_rdp.sh` | RDP 설정하는 조원 모두 |
| `handoff_prompt.md` | RDP 설정을 Claude에게 안내받을 조원 (내용을 Claude 채팅에 붙여 넣기) |
| `mqtt_cam/ir_sender.py` | 22번 담당 |
| `mqtt_cam/fusion_receiver.py` | 49번 담당 |
| `comm_bench/bench_server.py` | 49번 담당 |
| `comm_bench/bench_client.py` | 22번 담당 |
| `comm_bench/README.md` | 통신 비교 담당 |

- 주지 않아도 되는 것: `research/`(작업 기록), `comm_bench/results/`(노트북 시험 결과라 의미 없음)
- `setup_rdp.sh`는 메모장으로 열어 저장하지 말 것. 줄바꿈이 바뀌면 Pi에서 `$'\r': command not found` 오류가 난다.

## 1단계 원격 데스크톱(RDP) 설정

Pi 한 대당 노트북 하나만 작업한다. 아래 `<IP>`를 맡은 Pi IP(예: 192.168.20.23)로 바꾼다.

1. 스크립트 복사: `scp .\setup_rdp.sh linux@<IP>:~/`
2. 설치 후 재부팅: `ssh -t linux@<IP> "bash ~/setup_rdp.sh && sudo reboot"`
   1. 끝부분에 `[OK] xrdp 실행 중`, `[OK] 3389 포트(RDP) 대기 중`, `[OK] RDP 데스크톱: Raspberry Pi Desktop (X11)`, `[OK] 이미지 로더(PNG/SVG) 등록됨`이 나오면 성공
   2. 카메라 미연결 경고는 무시
3. 재부팅 1\~2분 뒤: Win+R → `mstsc` → `<IP>` → Session을 **Xorg**로 고르고 linux로 로그인
4. 상태만 점검: `ssh linux@<IP> "bash ~/setup_rdp.sh --check"`

내 Pi IP를 모를 때는 후보 IP에 ping을 보내 응답하는 것을 찾고, `ssh linux@<IP> "hostname; cat /proc/device-tree/model"`로 확인한다.

## 2단계 MQTT 브로커 설치와 통신 테스트

49번에 브로커(mosquitto)를 두고, 22번과 49번이 모두 그 브로커를 거쳐 메시지를 주고받는다. 기본 설정은 자기 자신만 받으므로 공유기 안 다른 기기를 허용하는 설정을 추가한다.

1. 49번 브로커 설치·설정:

```powershell
ssh -t linux@192.168.20.49 "sudo apt update && sudo apt install -y mosquitto mosquitto-clients && printf 'listener 1883 0.0.0.0\nallow_anonymous true\nset_tcp_nodelay true\n' | sudo tee /etc/mosquitto/conf.d/lan.conf && sudo systemctl restart mosquitto && sudo systemctl enable mosquitto"
```

2. 22번 클라이언트 설치: `ssh -t linux@192.168.20.22 "sudo apt update && sudo apt install -y mosquitto-clients"`
3. 테스트 (창 2개):
   1. 창 A(49번 대기): `ssh linux@192.168.20.49 "mosquitto_sub -h localhost -t test/hello -v"`
   2. 창 B(22번 전송): `ssh linux@192.168.20.22 "mosquitto_pub -h 192.168.20.49 -t test/hello -m 'hi from 22'"`
   3. 창 A에 `test/hello hi from 22`가 뜨면 성공

`allow_anonymous true`는 같은 공유기 안에서 테스트하는 용도다. 비밀번호 없이 누구나 접속할 수 있다. `set_tcp_nodelay true`는 작은 메시지가 묶여 늦게 가는 것(Nagle)을 막는다.

## 3단계 카메라 통합 코드와 브라우저 보기

카메라가 오기 전이라 가짜 영상으로 돌아간다. 카메라가 오면 두 파일 모두 `--source pi`를 붙여 실행하면 picamera2로 실제 촬영한다.

1. 라이브러리 설치(두 Pi 모두): `ssh -t linux@<IP> "sudo apt install -y python3-opencv python3-numpy python3-paho-mqtt"`
2. 복사: `scp .\mqtt_cam\ir_sender.py linux@192.168.20.22:~/` , `scp .\mqtt_cam\fusion_receiver.py linux@192.168.20.49:~/`
3. 창 A(49번 수신·통합): `ssh -t linux@192.168.20.49 "python3 ~/fusion_receiver.py"`
4. 창 B(22번 송신): `ssh -t linux@192.168.20.22 "python3 ~/ir_sender.py"`
5. 브라우저에서 `http://192.168.20.49:8080` 을 열면 `RGB | IR | 통합` 세 화면이 실시간으로 나온다.

창 A에 5초마다 `RGB 10.0 fps | IR 수신 9.9 fps | 짝 성공 100% | 평균 |dt| … ms` 가 나오면 정상이다. dt는 짝지은 RGB와 IR의 촬영 시각 차이다. 현재 약 112 ms이고, RGB를 0.1초 늦게 짝지으면 50 ms 아래로 줄일 수 있다(아직 미적용).

두 카메라 위치가 달라 생기는 화면 어긋남은 실제 카메라로 보정 행렬(호모그래피)을 구한 뒤 `--homography H.npy`로 넣는다.

## 4단계 통신 방식 비교

텍스트 메시지를 22번이 보내고 49번이 그대로 돌려주는 왕복 시간을 22번 시계 하나로 재므로, 두 Pi의 시계 차이는 결과에 영향을 주지 않는다. 자세한 설명은 `comm_bench/README.md`에 있다.

| 방식 | 내용 |
| --- | --- |
| `tcp` | 연결 재사용, 4바이트 길이 헤더, TCP\_NODELAY |
| `udp` | 시퀀스 번호로 응답 매칭, 타임아웃이면 손실 |
| `http-keepalive` | HTTP/1.1 연결 재사용 |
| `http-new` | 요청마다 새 연결 |
| `mqtt-qos0` | 브로커 경유, 전달 보장 없음 |
| `mqtt-qos1` | 브로커 경유, 최소 1회 전달 보장 |

측정 항목은 왕복 지연(평균·중앙값·p95·p99·최대), 초당 메시지 수, 손실률이고 16B·256B·1KB·8KB 크기별로 따로 잰다.

1. 카메라 프로그램(`ir_sender.py`, `fusion_receiver.py`)은 꺼 둔다.
2. 복사: `scp .\comm_bench\bench_server.py linux@192.168.20.49:~/` , `scp .\comm_bench\bench_client.py linux@192.168.20.22:~/`
3. 창 A(49번 서버): `ssh -t linux@192.168.20.49 "python3 ~/bench_server.py"` → `Echo ready`가 뜨면 다음으로
4. 창 B(22번 측정, 몇 분 걸림): `ssh -t linux@192.168.20.22 "python3 ~/bench_client.py"`
5. 결과 가져오기: `scp 'linux@192.168.20.22:~/results/bench_*.csv' .\comm_bench\results\`

Wi-Fi 상태에 따라 값이 흔들리므로 2\~3번 반복해서 비교한다. 예상되는 경향은 TCP·UDP가 가장 빠르고, MQTT는 브로커를 한 번 더 거치며, HTTP 새 연결은 연결을 맺는 비용이 더 든다.

## 49번을 다른 Pi로 바꿀 때

코드는 고칠 필요 없다. 새 Pi에 브로커를 설치하고, 22번 쪽 명령에 새 IP를 옵션으로 넘기면 된다. 아래 `<새IP>`를 바꾼다.

1. 새 Pi에 2단계 1번 명령을 IP만 바꿔 실행해 브로커를 설치한다.
2. 새 Pi에 3단계 1번 라이브러리를 설치하고, 49번용 파일(`fusion_receiver.py`, `bench_server.py`)을 새 Pi로 복사한다. 이 둘은 자기 자신의 브로커(localhost)를 쓰므로 그대로 실행한다.
3. 22번 명령에는 새 IP를 붙인다.
   1. 카메라: `ssh -t linux@192.168.20.22 "python3 ~/ir_sender.py --broker <새IP>"`
   2. 통신 비교: `ssh -t linux@192.168.20.22 "python3 ~/bench_client.py --host <새IP> --broker <새IP>"`
4. 브라우저 보기 주소도 `http://<새IP>:8080` 으로 바뀐다.

역할을 바꿔 22번을 브로커로 쓰는 것도 같은 방식으로 된다.

## 문제 해결

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `ssh: connect ... Connection timed out` | Pi가 꺼졌거나 네트워크에서 빠짐 | 전원 LED 확인, 재부팅, 랜선 연결, 모니터로 Wi-Fi 확인 |
| `stat local ... No such file or directory` | `comm_data` 폴더 밖에서 실행 | `cd <저장소 경로>\comm_data` 후 다시 |
| `$'\r': command not found` | `setup_rdp.sh` 줄바꿈이 Windows 방식으로 바뀜 | `ssh linux@<IP> "sed -i 's/\r$//' ~/setup_rdp.sh"` 후 다시 설치 |
| `Connection refused` (MQTT) | 브로커 설정이 안 들어감 | `ssh linux@<IP> "systemctl status mosquitto --no-pager; cat /etc/mosquitto/conf.d/lan.conf"` 로 확인 |
| 통합 창에 `IR 프레임이 안 온다` | 22번 `ir_sender.py`가 꺼져 있음 | 22번 창에서 다시 실행 |
| 프로그램이 몇 초마다 끊겼다 붙음 | 같은 MQTT 클라이언트 ID가 두 곳에서 접속 | 최신 코드는 기기마다 다른 ID를 쓰므로, 예전 파일이면 다시 복사 |
| RDP 화면이 검게 나옴 | 데스크톱 설정 문제 | mstsc를 켜 둔 채 `ssh linux@<IP> "bash ~/setup_rdp.sh --screenshot"` 출력 확인 |
| RDP 위쪽 작업표시줄이 안 보임 | 패널 설정 꼬임 | `ssh linux@<IP> 'mv ~/.config/lxpanel-pi ~/.config/lxpanel-pi.bak 2>/dev/null; echo done'` 후 RDP 안에서 `lxsession-logout`, 다시 접속 |
