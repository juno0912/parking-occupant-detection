# Copies pi-eth0-setup.sh to both Pis and runs it with sudo (asks each Pi's sudo password once).
$map = [ordered]@{ '192.168.20.22' = '10.10.10.22'; '192.168.20.10' = '10.10.10.10' }
foreach ($ip in $map.Keys) {
    scp -q "$PSScriptRoot\pi-eth0-setup.sh" "linux@${ip}:/tmp/pi-eth0-setup.sh"
    Write-Host "== linux@$ip : enter sudo password ==" -ForegroundColor Cyan
    ssh -t "linux@$ip" "sed -i 's/\r$//' /tmp/pi-eth0-setup.sh && sudo bash /tmp/pi-eth0-setup.sh $($map[$ip])"
}
Write-Host "Done." -ForegroundColor Green
