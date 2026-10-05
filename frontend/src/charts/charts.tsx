import { hhmm, ddmm, minutes, pct } from "../format";
import type { EquipmentView, ParetoReason, ShiftKpi } from "../types";
import { C, Chart, axis, base } from "./echarts";

const KIND_COLOR: Record<ParetoReason["kind"], string> = {
  equipment: C.bad,
  planned: C.info,
  micro: C.warn,
  setup: "#7a8fb0",
  flow: "#b7c0c9",
};

/** Парето причин простоя: горизонтальные столбики по минутам, цвет — тип остановки. */
export function ParetoChart({ reasons, height = 260 }: { reasons: ParetoReason[]; height?: number }) {
  const top = reasons.slice(0, 8).reverse();
  return (
    <Chart
      style={{ height }}
      option={{
        ...base,
        grid: { left: 150, right: 130, top: 8, bottom: 8 },
        tooltip: {
          ...base.tooltip,
          trigger: "item",
          formatter: (p: { dataIndex: number }) => {
            const r = top[p.dataIndex]!;
            return `<b>${r.reason_text}</b><br/>${minutes(r.minutes)}, ${r.count} раз, ${pct(r.share, 0)} всех потерь`;
          },
        },
        xAxis: { type: "value", show: false },
        yAxis: {
          type: "category",
          data: top.map((r) => r.reason_text),
          ...axis,
          axisLine: { show: false },
          axisLabel: { color: C.ink, fontSize: 13, width: 140, overflow: "truncate" },
        },
        series: [
          {
            type: "bar",
            barWidth: 16,
            data: top.map((r) => ({ value: Math.round(r.minutes), itemStyle: { color: KIND_COLOR[r.kind], borderRadius: 3 } })),
            label: {
              show: true,
              position: "right",
              color: C.ink,
              fontSize: 12,
              formatter: (p: { value: number; dataIndex: number }) => `${minutes(p.value)}, ${top[p.dataIndex]!.count} раз`,
            },
          },
        ],
      }}
    />
  );
}

/** OEE по сменам с линией цели и брак столбиками с нормой. */
export function ShiftHistoryChart({
  history,
  oeeTarget,
  defectMax,
  height = 230,
}: {
  history: ShiftKpi[];
  oeeTarget: number;
  defectMax: number;
  height?: number;
}) {
  const labels = history.map((h) => `${h.date.slice(8, 10)}.${h.date.slice(5, 7)} ${h.shift}`);
  return (
    <Chart
      style={{ height }}
      option={{
        ...base,
        grid: { left: 44, right: 44, top: 28, bottom: 30 },
        legend: { top: 0, right: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: C.muted } },
        xAxis: { type: "category", data: labels, ...axis, axisLabel: { color: C.muted, fontSize: 11 } },
        yAxis: [
          { type: "value", min: 0.6, max: 1, ...axis, axisLabel: { color: C.muted, formatter: (v: number) => pct(v, 0) } },
          {
            type: "value",
            min: 0,
            max: (v: { max: number }) => Math.max(0.08, v.max * 1.2),
            ...axis,
            splitLine: { show: false },
            axisLabel: { color: C.muted, formatter: (v: number) => pct(v, 0) },
          },
        ],
        tooltip: { ...base.tooltip, valueFormatter: (v: number) => pct(v) },
        series: [
          {
            name: "Брак",
            type: "bar",
            yAxisIndex: 1,
            barWidth: 10,
            data: history.map((h) => ({
              value: h.defect_rate,
              itemStyle: { color: h.defect_rate > defectMax ? "#eaa49e" : "#c9d1d9", borderRadius: 2 },
            })),
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: C.bad, type: "dashed" },
              label: { formatter: `норма ${pct(defectMax, 0)}`, color: C.bad, position: "insideEndTop" },
              data: [{ yAxis: defectMax }],
            },
          },
          {
            name: "OEE",
            type: "line",
            data: history.map((h) => h.oee),
            symbolSize: 6,
            lineStyle: { color: C.steel, width: 2 },
            itemStyle: { color: C.steel },
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: C.ok, type: "dashed" },
              label: { formatter: `цель ${pct(oeeTarget, 0)}`, color: C.ok, position: "insideStartTop" },
              data: [{ yAxis: oeeTarget }],
            },
          },
        ],
      }}
    />
  );
}

/** Телеметрия оборудования за последние часы с коридором нормы (±3σ). */
/** Скользящее среднее по 5 минутам — шум датчика меньше, тренд и предвестник видны лучше. */
function smooth(xs: number[], w = 5): number[] {
  return xs.map((_, i) => {
    const a = xs.slice(Math.max(0, i - w + 1), i + 1);
    return Math.round((a.reduce((s, v) => s + v, 0) / a.length) * 100) / 100;
  });
}

export function TelemetryChart({ eq, height = 250 }: { eq: EquipmentView; height?: number }) {
  const raw = eq.telemetry_series;
  const s = { ...raw, current: smooth(raw.current), vibration: smooth(raw.vibration) };
  const ts = s.ts.map(hhmm);
  const isBooth = s.filter_dp !== null;
  const norm = eq.telemetry_norm;
  const band = (k: string) => {
    const n = norm[k];
    return n ? [{ yAxis: n.mean - 3 * n.std }, { yAxis: n.mean + 3 * n.std }] : [];
  };
  const series = isBooth
    ? [
        {
          name: "Перепад давления на фильтре, Па",
          type: "line",
          data: s.filter_dp,
          showSymbol: false,
          lineStyle: { color: C.signal, width: 2 },
          itemStyle: { color: C.signal },
          markLine: {
            silent: true,
            symbol: "none",
            data: [
              {
                yAxis: eq.filter?.dp_defect_from_pa ?? 300,
                lineStyle: { color: C.warn, type: "dashed" },
                label: { formatter: "выше — растёт сорность", color: C.warn, position: "insideStartTop" },
              },
              {
                yAxis: eq.filter?.dp_limit_pa ?? 450,
                lineStyle: { color: C.bad, type: "dashed" },
                label: { formatter: "предел — остановка", color: C.bad, position: "insideStartTop" },
              },
            ],
          },
        },
      ]
    : [
        {
          name: "Ток привода, А",
          type: "line",
          data: s.current,
          showSymbol: false,
          lineStyle: { color: C.steel, width: 1.6 },
          itemStyle: { color: C.steel },
          markArea: { silent: true, itemStyle: { color: "rgba(23,146,79,0.06)" }, data: [band("current")] },
        },
        {
          name: "Вибрация, мм/с",
          type: "line",
          yAxisIndex: 1,
          data: s.vibration,
          showSymbol: false,
          lineStyle: { color: C.signal, width: 1.6 },
          itemStyle: { color: C.signal },
        },
      ];
  return (
    <Chart
      style={{ height }}
      option={{
        ...base,
        grid: { left: 44, right: isBooth ? 16 : 44, top: 30, bottom: 28 },
        legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: C.muted } },
        xAxis: { type: "category", data: ts, ...axis, axisLabel: { color: C.muted, interval: Math.floor(ts.length / 6) } },
        yAxis: isBooth
          ? [{ type: "value", min: 0, max: 500, ...axis }]
          : [
              { type: "value", scale: true, ...axis },
              { type: "value", scale: true, ...axis, splitLine: { show: false } },
            ],
        series,
      }}
    />
  );
}

export { ddmm };
