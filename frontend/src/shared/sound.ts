// Сигнал тревоги без аудиофайлов: Web Audio, два тона. Браузер разрешает звук после первого клика (вход в систему).
let ctx: AudioContext | null = null;

function tone(c: AudioContext, freq: number, start: number, dur: number, vol: number) {
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = "sine";
  o.frequency.value = freq;
  g.gain.setValueAtTime(0, start);
  g.gain.linearRampToValueAtTime(vol, start + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  o.connect(g).connect(c.destination);
  o.start(start);
  o.stop(start + dur + 0.05);
}

export function playAlarm(level: "critical" | "normal" = "critical") {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    const t = ctx.currentTime;
    if (level === "critical") {
      for (let i = 0; i < 3; i++) {
        tone(ctx, 880, t + i * 0.32, 0.14, 0.25);
        tone(ctx, 660, t + i * 0.32 + 0.15, 0.14, 0.25);
      }
    } else {
      tone(ctx, 740, t, 0.18, 0.15);
    }
  } catch {
    /* звук не критичен */
  }
}
