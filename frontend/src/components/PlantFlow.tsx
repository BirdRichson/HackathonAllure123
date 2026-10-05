import { Fragment } from "react";

import type { Area, Equipment, Plant } from "../types";

const AREA_NOTE: Record<string, string> = {
  WH: "Поставки CKD-комплектов",
  QC: "Финальный контроль",
  FG: "Готовые автомобили",
};

function EquipmentRow({ eq }: { eq: Equipment }) {
  return (
    <li className="flex items-center justify-between gap-2 rounded border border-line bg-panel-2 px-2.5 py-1.5">
      <span className="font-medium">{eq.name}</span>
      {eq.source === "assumption" && (
        <span className="text-xs text-muted" title="Нет в данных организаторов — допущение модели">
          допущение
        </span>
      )}
    </li>
  );
}

function AreaCard({ area, equipment }: { area: Area; equipment: Equipment[] }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col rounded-md border border-line bg-panel p-4">
      <div className="mb-3">
        <div className="text-lg font-semibold">{area.name}</div>
        <div className="font-mono text-sm text-muted">{area.line_id ?? AREA_NOTE[area.id] ?? ""}</div>
      </div>
      {equipment.length > 0 ? (
        <ul className="flex flex-col gap-1.5 text-sm">
          {equipment.map((eq) => (
            <EquipmentRow key={eq.id} eq={eq} />
          ))}
        </ul>
      ) : (
        <div className="text-sm text-muted">{area.line_id ? "" : "Участок без оборудования в данных"}</div>
      )}
    </div>
  );
}

export function PlantFlow({ plant }: { plant: Plant }) {
  const areas = plant.flow
    .map((id) => plant.areas.find((a) => a.id === id))
    .filter((a): a is Area => Boolean(a));

  return (
    <div className="flex items-stretch gap-2">
      {areas.map((area, i) => (
        <Fragment key={area.id}>
          {i > 0 && (
            <div className="flex items-center text-2xl text-muted" aria-hidden>
              →
            </div>
          )}
          <AreaCard area={area} equipment={plant.equipment.filter((e) => e.area === area.id)} />
        </Fragment>
      ))}
    </div>
  );
}
