export function expenseToday(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Kolkata",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(now);
  const part = (type: string) => parts.find((p) => p.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
export function expenseMonth(offset = 0, now = new Date()): string {
  const [year, month] = expenseToday(now).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1 + offset, 1)).toISOString().slice(0, 7);
}
export function fuelMileage(distance: string, liters: string): number | null {
  const km = Number(distance), fuel = Number(liters);
  return Number.isFinite(km) && Number.isFinite(fuel) && km > 0 && fuel > 0 ? km / fuel : null;
}
