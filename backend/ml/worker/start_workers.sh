#!/bin/sh
# (Пере)запускает воркеры на стенде LinQ в фоне. Из корня бандла cvhack_worker в терминале Jupyter
# или из linq-vpn: ljup sh 'sh ~/work/cvhack_worker/backend/ml/worker/start_workers.sh'
# TPU стенда обслуживает запросы параллельно: 4 воркера на одной очереди дают ~10 кадр/с, один — ~3.
# MODELS — какие модели из data/models гонять на каждом кадре (по умолчанию все, у которых есть meta.json).
set -e
cd "$(dirname "$0")/../../.."
WORKERS=${WORKERS:-4}
PROGRAM_DIR=${PROGRAM_DIR:-/auto/cache/$USER}
MODELS=${MODELS:-$(for d in data/models/*/meta.json; do basename "$(dirname "$d")"; done)}
args=""
for m in $MODELS; do
  tpu=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['files']['tpu'])" "data/models/$m/meta.json")
  # сервис TPU читает программы только из /auto/cache/<логин>
  [ -f "$PROGRAM_DIR/$tpu" ] || cp "data/models/$m/$tpu" "$PROGRAM_DIR/"
  args="$args --model-dir data/models/$m"
done
pkill -f backend/ml/worker/linq_worker.py || true
mkdir -p logs
for i in $(seq 1 "$WORKERS"); do
  # shellcheck disable=SC2086
  setsid nohup python3 backend/ml/worker/linq_worker.py $args --program-dir "$PROGRAM_DIR" \
    > "logs/worker-$i.log" 2>&1 < /dev/null &
done
sleep 5
grep -h "Models:\|Listening" logs/worker-1.log
grep -c "Listening" logs/worker-*.log | grep -q ":0" && { tail -n 20 logs/worker-*.log; exit 1; }
echo "воркеров: $(pgrep -fc backend/ml/worker/linq_worker.py)"
