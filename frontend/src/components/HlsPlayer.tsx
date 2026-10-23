import { useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { VideoCameraOutlined } from "@ant-design/icons";

/** Живое видео из MediaMTX (HLS). Если поток не поднялся — показываем последний кадр камеры. */
export default function HlsPlayer({ src, poster, fallback }: { src: string | null; poster?: string; fallback?: JSX.Element }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(!src);

  useEffect(() => {
    const v = ref.current;
    if (!v || !src) return;
    setFailed(false);
    if (v.canPlayType("application/vnd.apple.mpegurl")) {
      v.src = src;
      return;
    }
    if (!Hls.isSupported()) {
      setFailed(true);
      return;
    }
    const hls = new Hls({ liveSyncDuration: 2, maxLiveSyncPlaybackRate: 1.5, lowLatencyMode: true });
    hls.loadSource(src);
    hls.attachMedia(v);
    hls.on(Hls.Events.ERROR, (_e, d) => d.fatal && setFailed(true));
    return () => hls.destroy();
  }, [src]);

  if (failed) return fallback || <div className="video-empty"><VideoCameraOutlined /> Нет видеопотока</div>;
  return <video ref={ref} className="live-video" muted autoPlay playsInline poster={poster} onError={() => setFailed(true)} />;
}
