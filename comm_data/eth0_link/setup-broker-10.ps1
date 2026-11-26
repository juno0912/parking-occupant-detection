# Copies broker-setup-10.sh to rpi-lyb3550 and runs it with sudo (asks the sudo password once).
scp -q "$PSScriptRoot\broker-setup-10.sh" "linux@192.168.20.10:/tmp/broker-setup-10.sh"
Write-Host "== linux@192.168.20.10 : enter sudo password ==" -ForegroundColor Cyan
ssh -t "linux@192.168.20.10" "sed -i 's/\r$//' /tmp/broker-setup-10.sh && sudo bash /tmp/broker-setup-10.sh"
Write-Host "Done." -ForegroundColor Green
