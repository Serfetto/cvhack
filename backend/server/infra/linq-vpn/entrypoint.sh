#!/bin/sh
# Поднимает VPN до стенда LinQ; маршрут только в 10.0.114.0/24, остальной трафик идёт мимо туннеля
set -e
[ -f /vpn/client.ovpn ] || { echo "нет /vpn/client.ovpn (artifacts/Hakathon.ovpn)"; exit 1; }
[ -f /vpn/auth.txt ] || { echo "нет /vpn/auth.txt (secrets/vpn-auth.txt: логин и пароль по строке)"; exit 1; }
# пробросы для остальных контейнеров compose (VPN есть только здесь): «порт:хост_стенда:порт», по умолчанию RabbitMQ
for f in ${LINQ_FORWARDS-5672:10.0.114.30:5672}; do
  socat TCP-LISTEN:"${f%%:*}",fork,reuseaddr TCP:"${f#*:}" &
done
exec openvpn --config /vpn/client.ovpn --auth-user-pass /vpn/auth.txt --auth-nocache \
  --script-security 2 --up /usr/local/bin/vpn-up.sh --up-restart
