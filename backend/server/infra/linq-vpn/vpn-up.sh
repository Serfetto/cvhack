#!/bin/sh
# up-скрипт OpenVPN: split DNS — *.lin-q.ru через DNS из туннеля (dhcp-option DNS), остальное через DNS Docker
dns=$(env | sed -n 's/^foreign_option_[0-9]*=dhcp-option DNS //p' | head -n1)
[ -n "$dns" ] || exit 0
[ -f /etc/resolv.conf.docker ] || cp /etc/resolv.conf /etc/resolv.conf.docker
upstream=$(sed -n 's/^nameserver //p' /etc/resolv.conf.docker | sed 's/^/--server=/')
[ -f /run/dnsmasq.pid ] && kill "$(cat /run/dnsmasq.pid)" 2>/dev/null
# shellcheck disable=SC2086
dnsmasq --no-resolv --no-hosts --listen-address=127.0.0.1 --bind-interfaces --pid-file=/run/dnsmasq.pid \
  --server=/lin-q.ru/"$dns" $upstream
{ echo "nameserver 127.0.0.1"; grep -v '^nameserver' /etc/resolv.conf.docker; } > /etc/resolv.conf
echo "split DNS: lin-q.ru -> $dns, остальное -> $(echo $upstream | sed 's/--server=//g')"
