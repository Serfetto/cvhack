FROM alpine:3.20
RUN apk add --no-cache ffmpeg bash
COPY run.sh /run.sh
RUN chmod +x /run.sh
ENTRYPOINT ["/run.sh"]
