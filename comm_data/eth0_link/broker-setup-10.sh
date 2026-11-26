#!/bin/bash
# Run on rpi-lyb3550 (192.168.20.10) with sudo: installs MQTT broker + Python libs (guide step 2-1 and 3-1).
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq mosquitto mosquitto-clients python3-paho-mqtt python3-opencv python3-numpy >/dev/null
printf 'listener 1883 0.0.0.0\nallow_anonymous true\nset_tcp_nodelay true\n' > /etc/mosquitto/conf.d/lan.conf
systemctl enable mosquitto >/dev/null 2>&1
systemctl restart mosquitto
echo "BROKER_OK $(hostname): mosquitto $(systemctl is-active mosquitto)"
ss -ltn | grep 1883
