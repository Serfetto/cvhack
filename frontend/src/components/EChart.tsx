import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, MarkLineComponent, DatasetComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { useUi } from "@/store/ui";

echarts.use([BarChart, LineChart, HeatmapChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, MarkLineComponent, DatasetComponent, CanvasRenderer]);

export interface ChartClick {
  name: string;
  seriesName?: string;
  data: unknown;
  dataIndex: number;
}

/** Обёртка ECharts: подгоняет размер под контейнер и перерисовывается при смене темы. */
export default function EChart({ option, height = 300, onClick }: { option: EChartsCoreOption; height?: number; onClick?: (p: ChartClick) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts>();
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  const theme = useUi((s) => s.theme);

  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.current = c;
    c.on("click", (p) => clickRef.current?.(p as unknown as ChartClick));
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      c.dispose();
    };
  }, [theme]);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
    if (onClick) chart.current?.getZr().setCursorStyle("pointer");
  }, [option, theme, onClick]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}

/** Цвета осей и текста графиков для текущей темы. */
export function useChartInk() {
  const dark = useUi((s) => s.theme) === "dark";
  return {
    dark,
    text: dark ? "#c3c2b7" : "#52514e",
    muted: "#898781",
    grid: dark ? "#2c2c2a" : "#e9edf3",
    axis: dark ? "#383835" : "#c3c2b7",
    surface: dark ? "#131924" : "#ffffff",
    tooltip: {
      backgroundColor: dark ? "#1b2230" : "#ffffff",
      borderColor: dark ? "#2c3442" : "#e5e7eb",
      textStyle: { color: dark ? "#f0efec" : "#0b0b0b", fontSize: 12 },
      extraCssText: "border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.12);",
    },
  };
}
