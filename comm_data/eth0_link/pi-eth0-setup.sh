#!/bin/bash
# Usage: sudo bash pi-eth0-setup.sh <eth0-ip>   e.g. 10.10.10.22
# Installs iperf3 and gives eth0 a static IP for the direct cable link (Wi-Fi stays the default route).
set -e
IP="$1"
[ -n "$IP" ] || { echo "need IP"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
echo "iperf3 iperf3/start_daemon boolean false" | debconf-set-selections
apt-get install -y iperf3 >/dev/null && echo "iperf3 installed: $(iperf3 --version | head -1)"
nmcli con delete p2p-eth0 >/dev/null 2>&1 || true
nmcli con add type ethernet ifname eth0 con-name p2p-eth0 \
  ipv4.method manual ipv4.addresses "$IP/24" ipv4.never-default yes \
  ipv6.method link-local connection.autoconnect yes connection.autoconnect-priority 100 >/dev/null
nmcli con up p2p-eth0 >/dev/null
echo "SETUP_OK $(hostname): $(ip -br -4 addr show eth0)"
