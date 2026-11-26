# 다른 노트북의 Claude 에게 붙여 넣을 내용

아래 "---" 사이를 그대로 복사해서 다른 노트북의 Claude 앱 채팅에 붙여 넣는다.
붙여 넣기 전에 setup_rdp.sh 를 그 노트북의 작업 폴더에 복사해 둔다 (메모장으로 열어 저장하지 말 것).

---
라즈베리파이 4B 여러 대에 Windows 기본 "원격 데스크톱 연결"(mstsc)로 접속할 수 있게 설정하는 중이야.
설정은 이미 완성된 스크립트 setup_rdp.sh 로 하고, 이 폴더에 있어. 너는 스크립트를 고치지 말고, 내가 실행할 명령을 안내하고 결과를 해석해 줘.

## 환경
- Pi: Raspberry Pi 4B, Raspberry Pi OS (Debian 13 trixie), 계정 linux, 같은 공유기 네트워크
- 내가 맡은 Pi IP: <여기에 IP>
- 노트북: Windows, PowerShell, 기본 ssh/scp 사용

## 중요한 제약
- ssh/scp 는 비밀번호를 물어보니, 명령은 네가 실행하지 말고 내가 PowerShell 에서 직접 실행하게 코드 블록으로 줘.
- 같은 Pi 를 다른 노트북에서도 동시에 작업하지 않는다 (Pi 마다 노트북 하나).

## 진행 순서
1. 복사:   scp .\setup_rdp.sh linux@<IP>:~/
2. 설치:   ssh -t linux@<IP> "bash ~/setup_rdp.sh && sudo reboot"
   - 처음 접속이면 "continue connecting" 질문에 yes 를 끝까지 입력
   - 끝부분 점검에서 확인할 줄:
     [OK] xrdp 실행 중 / [OK] 3389 포트(RDP) 대기 중 / [OK] RDP 데스크톱: Raspberry Pi Desktop (X11) / [OK] 이미지 로더(PNG/SVG) 등록됨
   - 카메라 미연결 경고는 무시해도 됨
3. 재부팅 1~2분 뒤: Win+R → mstsc → <IP> → 로그인 화면에서 Session: Xorg → linux 로그인
4. 정상 화면: Raspberry Pi 배경화면(주황색 산), 바탕화면 아이콘(Chromium, Firefox, VS Code, LXTerminal, Mousepad), 위쪽 작업표시줄

## 문제별 대응 (이미 겪은 것들)
- "$'\r': command not found" → 줄바꿈 문제:  ssh linux@<IP> "sed -i 's/\r$//' ~/setup_rdp.sh" 후 2번 다시
- 화면 양옆에 흰 띠 → 빈 패널임. 흰 띠에서 우클릭 → Delete Panel
- 위쪽 작업표시줄이 안 보임 → ssh linux@<IP> 'mv ~/.config/lxpanel-pi ~/.config/lxpanel-pi.bak 2>/dev/null; echo done'
  그 다음 RDP 안 터미널에서 lxsession-logout 후 다시 접속
- 화면이 검게 나옴 → mstsc 접속을 켜 둔 채로  ssh linux@<IP> "bash ~/setup_rdp.sh --screenshot"  출력을 보고 판단
  (출력의 창 목록, GTK 모니터 크기, 바탕화면 설정을 확인)
- 로그아웃: 작업표시줄 메뉴의 Logout, 또는 RDP 안 터미널에서 lxsession-logout
- 상태만 점검: ssh linux@<IP> "bash ~/setup_rdp.sh --check"
- "[오류]" 가 나오면 그 줄과 바로 위 apt 메시지를 보고 원인을 설명해 줘. 스크립트는 고치지 말고 나한테 알려 줘.

먼저 1번 명령부터 안내해 줘.
---
