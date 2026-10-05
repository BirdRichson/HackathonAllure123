import { BarChart, CustomChart, LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/lib/core";
import type { CSSProperties } from "react";

echarts.use([
  BarChart,
  LineChart,
  CustomChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkAreaComponent,
  DataZoomComponent,
  SVGRenderer,
]);

export const C = {
  ink: "#1c2630",
  muted: "#59656f",
  faint: "#8b96a1",
  line: "#d2d8de",
  grid: "#eceff2",
  signal: "#ef8a14",
  steel: "#3d4955",
  ok: "#17924f",
  warn: "#d59a12",
  bad: "#d2352b",
  info: "#2c67cc",
};

/** Общие настройки: шрифт, оси, подсказки — в одном стиле на всех графиках. */
export const base = {
  textStyle: { fontFamily: "IBM Plex Sans, sans-serif", color: C.muted, fontSize: 12 },
  animation: false,
  tooltip: {
    trigger: "axis",
    backgroundColor: "#ffffff",
    borderColor: C.line,
    textStyle: { color: C.ink, fontSize: 13 },
  },
  grid: { left: 48, right: 16, top: 24, bottom: 28, containLabel: false },
};

export const axis = {
  axisLine: { lineStyle: { color: C.line } },
  axisTick: { show: false },
  axisLabel: { color: C.muted },
  splitLine: { lineStyle: { color: C.grid } },
};

export function Chart({ option, style }: { option: object; style?: CSSProperties }) {
  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      notMerge
      lazyUpdate
      opts={{ renderer: "svg" }}
      style={{ width: "100%", height: 240, ...style }}
    />
  );
}
