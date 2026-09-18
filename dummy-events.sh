#!/bin/bash
set -e

sudo rm -rf /usr/share/clockenstein/daemon
sudo rm -rf /usr/share/clockenstein/agent
sudo cp -R daemon agent /usr/share/clockenstein/
sudo cp calendar/store.py /usr/share/clockenstein/calendar/
sudo cp calendar/backends/*.py /usr/share/clockenstein/calendar/backends/
sudo rm -rf /usr/lib/python3/dist-packages/clockenstein
sed 's|@datadir@|/usr/share|' clockenstein/alarms.py > alarms.py.new
sudo cp -R clockenstein /usr/lib/python3/dist-packages/
sudo mv alarms.py.new /usr/lib/python3/dist-packages/clockenstein/alarms.py
sudo mkdir -p /usr/share/clockenstein/sounds
sudo cp data/notification.oga /usr/share/clockenstein/sounds/
systemctl --user restart clockenstein-daemon.service
systemctl --user restart clockenstein-notification-agent.service
