# 라즈베리파이 Wi-Fi·유선 통신 비교

라즈베리파이 4B 두 대(22번 `rpi-syw3480`, 10번 `rpi-lyb3550`)를 Wi-Fi와 랜선 직결(eth0)로 연결하고, MQTT 카메라 통합과 6가지 통신 방식의 지연·처리량을 비교한 팀 프로젝트 자료입니다.

**핵심 결과 (2026-11-26, 경로별 3회 반복)**
- 유선 직결은 1GbE를 사실상 다 쓴다: iperf3 TCP 941 Mbps, UDP 952 Mbps, 손실 0%.
- 통신 방식 24개 조합 전부에서 유선이 Wi-Fi보다 왕복 지연이 5.1~37.0배 짧다 (TCP 16B: 2.05 ms → 0.178 ms).
- Wi-Fi는 8KB 메시지와 지연 꼬리(p99)에서 특히 불리하고, 회차마다 값이 흔들린다.

자세한 내용은 **[보고서 docs/report.md](docs/report.md)** 에 있습니다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| [docs/report.md](docs/report.md) | 최종 보고서 (목적·환경·방법·결과·분석·재현 방법) |
| [docs/라즈베리파이 RDP·MQTT·통신 비교 진행 가이드.md](<docs/라즈베리파이 RDP·MQTT·통신 비교 진행 가이드.md>) | 처음 작성한 진행 가이드 (RDP, MQTT, 49번 기준) |
| [eth0_link/](eth0_link/) | 유선 직결 설정 스크립트: SSH 키 등록, eth0 고정 IP, 10번 브로커 설치, iperf3 측정, 결과 로그 |
| [comm_bench/](comm_bench/) | 통신 방식 비교 벤치마크 (서버·클라이언트), 그래프 스크립트, 결과 CSV·그래프 |
| [comm_bench/results/figures/](comm_bench/results/figures/) | 결과 그래프 PNG 6장 |
| [comm_bench/dashboard/index.html](comm_bench/dashboard/index.html) | 인터랙티브 대시보드 페이지 원본 (대시보드 링크는 별도 공유) |
| [mqtt_cam/](mqtt_cam/) | 카메라 통합 코드 (`ir_sender.py`, `fusion_receiver.py`)와 테스트 로그 |
| `setup_rdp.sh`, `handoff_prompt.md` | 원격 데스크톱(xrdp) 설정 스크립트와 안내 프롬프트 |

## 빠르게 다시 해 보기

자세한 단계는 보고서 7절에 있습니다. 노트북 PowerShell에서 이 `comm_data` 폴더로 이동해 실행합니다 (`cd comm_data`). 비밀번호(SSH, sudo)는 직접 입력합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\eth0_link\copy-ssh-key.ps1
```
```powershell
powershell -ExecutionPolicy Bypass -File .\eth0_link\setup-pis.ps1
```
```powershell
powershell -ExecutionPolicy Bypass -File .\eth0_link\setup-broker-10.ps1
```

그래프 다시 그리기 (Python, matplotlib, pandas 필요):
```powershell
python .\comm_bench\plot_results.py
```

## 주의
- 10번의 mosquitto 브로커는 익명 접속을 허용합니다. 같은 공유기 안 테스트용입니다.
- `setup_rdp.sh`와 `eth0_link/*.sh`는 메모장으로 저장하지 마세요. 줄바꿈이 바뀌면 Pi에서 `$'\r': command not found` 오류가 납니다.
- 카메라 테스트는 실제 카메라가 아닌 가짜 영상으로 했습니다.
