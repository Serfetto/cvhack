# OpenVPN-клиент до стенда LinQ (10.0.114.0/24) + инструменты для удалённого Jupyter hackathon.lin-q.ru
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openvpn dnsmasq-base iproute2 iputils-ping curl dnsutils openssh-client socat \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir requests==2.32.3 websocket-client==1.8.0

COPY entrypoint.sh vpn-up.sh /usr/local/bin/
COPY ljup.py /usr/local/bin/ljup
# скрипты могли прийти из Windows-чекаута с CRLF
RUN cd /usr/local/bin && sed -i 's/\r$//' entrypoint.sh vpn-up.sh ljup && chmod +x entrypoint.sh vpn-up.sh ljup

WORKDIR /work
ENTRYPOINT ["entrypoint.sh"]
