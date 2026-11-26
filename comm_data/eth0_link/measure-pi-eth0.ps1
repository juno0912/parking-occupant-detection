$ErrorActionPreference = 'Stop'

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$rawPath = Join-Path $PSScriptRoot "pi_eth0_$stamp.log"
$reportPath = Join-Path $PSScriptRoot "pi_eth0_$stamp.md"
Set-Content -LiteralPath $rawPath -Encoding UTF8 -Value "Started $(Get-Date -Format o)"

$preflight = @'
set -eu
exec 2>&1
export LC_ALL=C
echo "host=$(hostname) time=$(date -Iseconds)"
ip -br -4 addr show dev eth0
link=/sys/class/net/eth0
echo "eth0 speed=$(cat "$link/speed") Mbps duplex=$(cat "$link/duplex") mtu=$(cat "$link/mtu")"
route=$(ip -4 route get "$peer" from "$local")
echo "$route"
case " $route " in
    *" dev eth0 "*) ;;
    *) echo "ERROR: route to $peer does not use eth0"; exit 1 ;;
esac
iperf3 --version
echo "--- ping $local to $peer ---"
ping -4 -I "$local" -n -q -c 30 -i 0.2 -W 1 "$peer" || echo "ping status=$?"
'@

$server = @'
server_log=$(mktemp)
nohup timeout 300s bash -c 'trap '\''rm -f "$1"'\'' EXIT; for run in 1 2 3 4 5 6 7; do iperf3 -s -1 -B "$2" -p 5202 || exit; done' _ "$server_log" "$local" >"$server_log" 2>&1 </dev/null &
pid=$!
sleep 1
if ! kill -0 "$pid" 2>/dev/null; then
    echo 'ERROR: failed to start the iperf3 server on TCP port 5202'
    cat "$server_log" 2>/dev/null || true
    rm -f "$server_log"
    exit 1
fi
echo 'iperf3 server started on TCP 5202'
'@

$client = @'
run_test() {
    name=$1
    shift
    echo "--- tcp $name ---"
    timeout 25s iperf3 -4 -c "$peer" -B "$local" -p 5202 -t 10 -O 2 -P 1 -f m "$@" || echo "iperf3 status=$?"
    sleep 1
}
for run in 1 2 3; do
    run_test "22-to-10 $run"
    run_test "10-to-22 $run" -R
done
if iperf3 --help 2>&1 | grep -q -- --bidir; then
    run_test 'simultaneous 1' --bidir
fi
'@

function Invoke-Pi([string]$Address, [string]$RemoteScript) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($RemoteScript.Replace("`r", ''))
    $encoded = [Convert]::ToBase64String($bytes)
    Write-Host "Connecting to linux@$Address"
    & ssh -T -o ConnectTimeout=8 -o StrictHostKeyChecking=ask "linux@$Address" `
        "printf '%s' '$encoded' | base64 -d | bash" | ForEach-Object {
        Write-Host $_
        Add-Content -LiteralPath $rawPath -Encoding UTF8 -Value $_
    }
    if ($LASTEXITCODE -ne 0) {
        throw "SSH or remote preflight failed for $Address (exit $LASTEXITCODE). Raw log: $rawPath"
    }
}

Invoke-Pi '192.168.20.10' ("local=10.10.10.10; peer=10.10.10.22`n$preflight`n$server")
Invoke-Pi '192.168.20.22' ("local=10.10.10.22; peer=10.10.10.10`n$preflight`n$client")

$raw = Get-Content -Raw -LiteralPath $rawPath
$sections = [regex]::Split($raw, '(?m)^--- ')
$culture = [Globalization.CultureInfo]::InvariantCulture
$report = @(
    '# Raspberry Pi eth0 benchmark'
    ''
    "Measured $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'). [Raw output]($([IO.Path]::GetFileName($rawPath)))."
    ''
    'Management SSH used the 192.168.20.x addresses. Both endpoint route checks selected eth0 for the 10.10.10.x peer.'
    ''
    '## Link'
    ''
)
$report += [regex]::Matches($raw, '(?m)^(?:host=|eth0 speed=).+$') | ForEach-Object { '- ' + $_.Value.Trim() }
$report += @(
    ''
    '## Idle ping'
    ''
    '| Echo request direction | Sent | Received | Loss | RTT min / avg / max / mdev (ms) |'
    '|---|---:|---:|---:|---|'
)
foreach ($section in $sections | Where-Object { $_.StartsWith('ping ') }) {
    $direction = ([regex]::Match($section, '^ping (.*?) ---')).Groups[1].Value
    $counts = [regex]::Match($section, '(\d+) packets transmitted, (\d+) received, ([\d.]+)% packet loss')
    $rtt = [regex]::Match($section, 'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms')
    $rttText = if ($rtt.Success) { ($rtt.Groups | Select-Object -Skip 1).Value -join ' / ' } else { 'Unavailable' }
    if ($counts.Success) {
        $report += "| $direction | $($counts.Groups[1]) | $($counts.Groups[2]) | $($counts.Groups[3])% | $rttText |"
    } else {
        $report += "| $direction | - | - | - | Unavailable |"
    }
}
$report += @(
    ''
    '## TCP throughput'
    ''
    'One TCP stream per direction with 10 measured seconds after a 2-second warm-up. Rates are receiver-side Mbit/s.'
    ''
    '| Direction | Run 1 | Run 2 | Run 3 | Median | Completed |'
    '|---|---:|---:|---:|---:|---:|'
)
$receiverPattern = '(?m)^(?<line>[^\r\n]*?\s(?<rate>[\d.]+)\s+Mbits/sec[^\r\n]*?\sreceiver)\s*$'
foreach ($direction in '22-to-10', '10-to-22') {
    $samples = foreach ($run in 1..3) {
        $section = $sections | Where-Object { $_.StartsWith("tcp $direction $run ---") } | Select-Object -First 1
        $receiver = [regex]::Match([string]$section, $receiverPattern)
        if ($receiver.Success) { $receiver.Groups['rate'].Value } else { '-' }
    }
    $sorted = @($samples | Where-Object { $_ -ne '-' } | ForEach-Object { [double]::Parse($_, $culture) } | Sort-Object)
    $median = '-'
    if ($sorted.Count -eq 3) { $median = $sorted[1].ToString($culture) }
    $label = $direction.Replace('-to-', ' to ')
    $report += "| $label | $($samples -join ' | ') | $median | $($sorted.Count)/3 |"
}
$report += @('', '## Simultaneous TCP', '')
$simultaneous = $sections | Where-Object { $_.StartsWith('tcp simultaneous ') } | Select-Object -First 1
$receivers = [regex]::Matches([string]$simultaneous, $receiverPattern)
$directionLabels = @{ 'TX-C' = '22 to 10'; 'RX-C' = '10 to 22' }
foreach ($receiver in $receivers) {
    $role = [regex]::Match($receiver.Value, '\[(TX-C|RX-C)\]').Groups[1].Value
    if ($directionLabels.ContainsKey($role)) {
        $report += "- $($directionLabels[$role]) received $($receiver.Groups['rate']) Mbit/s."
    } else {
        $report += ('- ' + $receiver.Value.Trim())
    }
}
if ($receivers.Count -lt 2) { $report += 'A full pair of simultaneous measurements is unavailable. See the raw output.' }

Set-Content -LiteralPath $reportPath -Encoding UTF8 -Value $report
Write-Host "Report: $reportPath"
Write-Host "Raw log: $rawPath"
