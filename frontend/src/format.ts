// Форматирование чисел и времени по-русски. Время завода приходит в ISO с +05:00 —
// берём часы и дату прямо из строки, чтобы не зависеть от часового пояса ноутбука.

const nf = new Intl.NumberFormat("ru-RU");

export const num = (x: number | null | undefined, digits = 0): string =>
  x == null || Number.isNaN(x)
    ? "—"
    : new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(x);

export const int = (x: number | null | undefined): string => (x == null ? "—" : nf.format(Math.round(x)));

export const pct = (x: number | null | undefined, digits = 1): string => (x == null ? "—" : `${num(x * 100, digits)}%`);

export const hhmm = (iso: string | null | undefined): string => (iso ? iso.slice(11, 16) : "—");

export const ddmm = (iso: string | null | undefined): string => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}` : "—");

export const dateTime = (iso: string | null | undefined): string => (iso ? `${ddmm(iso)} ${hhmm(iso)}` : "—");

export function minutes(m: number | null | undefined): string {
  if (m == null) return "—";
  const total = Math.round(m);
  if (total < 60) return `${total} мин`;
  const h = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${h} ч ${rest} мин` : `${h} ч`;
}

export function hours(h: number): string {
  if (h < 1) return `${Math.round(h * 60)} мин`;
  return `${num(h, h < 10 ? 1 : 0)} ч`;
}

/** Минуты между двумя ISO-метками одного пояса. */
export const diffMin = (a: string, b: string): number => (Date.parse(b) - Date.parse(a)) / 60000;

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

export function longDate(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${WEEKDAYS[d.getUTCDay()]}`;
}
