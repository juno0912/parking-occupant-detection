# Registers this PC's SSH public key on both Raspberry Pis (asks each Pi's password once).
$pub = Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
foreach ($ip in '192.168.20.22', '192.168.20.10') {
    Write-Host "== linux@$ip : enter password ==" -ForegroundColor Cyan
    $pub | ssh -o StrictHostKeyChecking=accept-new "linux@$ip" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_OK on `$(hostname)"
}
Write-Host "Done." -ForegroundColor Green
