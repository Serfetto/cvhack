#!/usr/bin/env bash
# Имитация камер: каждый data/demo_videos/<имя>.mp4 крутится по кругу в rtsp://mediamtx:8554/<имя>.
# Для камер из CAMS, у которых нет видеофайла, идёт тестовая таблица (конвейер проверяется и без роликов).
set -u
RTSP="${RTSP_BASE:-rtsp://mediamtx:8554}"
CAMS="${CAMS:-cam01 cam02 cam03 cam04}"

stream_file() {  # $1 — файл, $2 — путь
  while true; do
    ffmpeg -hide_banner -loglevel error -re -stream_loop -1 -i "$1" -an -c:v copy -f rtsp -rtsp_transport tcp "$RTSP/$2" \
      || ffmpeg -hide_banner -loglevel error -re -stream_loop -1 -i "$1" -an -c:v libx264 -preset ultrafast -tune zerolatency \
           -g 25 -f rtsp -rtsp_transport tcp "$RTSP/$2"
    echo "[cams] $2: поток прервался, перезапуск через 2 с"; sleep 2
  done
}

stream_test() {  # $1 — путь
  while true; do
    ffmpeg -hide_banner -loglevel error -re -f lavfi -i "testsrc2=size=640x360:rate=10" -c:v libx264 -preset ultrafast \
      -tune zerolatency -g 10 -pix_fmt yuv420p -f rtsp -rtsp_transport tcp "$RTSP/$1"
    echo "[cams] $1: тестовый поток прервался, перезапуск через 2 с"; sleep 2
  done
}

sleep 2
declare -A started
for f in /videos/*.mp4; do
  [ -e "$f" ] || continue
  name="$(basename "$f" .mp4)"
  echo "[cams] $name ← $f"
  stream_file "$f" "$name" &
  started[$name]=1
done
for name in $CAMS; do
  if [ -z "${started[$name]:-}" ]; then
    echo "[cams] $name ← тестовая таблица (нет /videos/$name.mp4)"
    stream_test "$name" &
  fi
done
wait
