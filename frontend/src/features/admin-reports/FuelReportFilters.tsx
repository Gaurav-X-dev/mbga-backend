import { Button } from "../../components/common/Button";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";

export const FUEL_FILTER_KEYS = ["vehicleId","driverId","fuelType","recordedBy","destination","hasReceipt","telemetry","minAmount","maxAmount","minKmReading","maxKmReading","minDistance","maxDistance","minLiters","maxLiters","minMileage","maxMileage"] as const;
type Option = {value: string; label: string};

export function FuelReportFilters({values,metadata,onChange,onReset}: {
  values: Record<string,string>; metadata?: Record<string,unknown>;
  onChange: (key:string,value:string) => void; onReset: () => void;
}) {
  const options = (metadata?.fuelOptions ?? {}) as {vehicles?:Option[];drivers?:Option[];recorders?:Option[];fuelTypes?:Option[]};
  return <Card title="Fuel sheet filters">
    <div className="fuel-report-filter-grid">
      <div className="field"><span className="field__label" aria-hidden="true">Search</span>
        <SearchInput label="Search fuel records" placeholder="Vehicle, driver, destination or note" value={values.q} onChange={(e) => onChange("q",e.target.value)} />
      </div>
      <Field label="Vehicle"><Select value={values.vehicleId} onChange={(e) => onChange("vehicleId",e.target.value)} placeholder="All vehicles" options={options.vehicles ?? []} /></Field>
      <Field label="Driver"><Select value={values.driverId} onChange={(e) => onChange("driverId",e.target.value)} placeholder="All drivers" options={options.drivers ?? []} /></Field>
      <Field label="Fuel type"><Select value={values.fuelType} onChange={(e) => onChange("fuelType",e.target.value)} placeholder="All fuel types" options={options.fuelTypes ?? []} /></Field>
      <Field label="Recorded by"><Select value={values.recordedBy} onChange={(e) => onChange("recordedBy",e.target.value)} placeholder="All staff" options={options.recorders ?? []} /></Field>
      <Field label="Destination"><Input value={values.destination} onChange={(e) => onChange("destination",e.target.value)} maxLength={160} placeholder="Any destination" /></Field>
      <Field label="Receipt"><Select value={values.hasReceipt} onChange={(e) => onChange("hasReceipt",e.target.value)} placeholder="All receipts" options={[{value:"true",label:"Attached"},{value:"false",label:"Not attached"}]} /></Field>
      <Field label="Fuel details"><Select value={values.telemetry} onChange={(e) => onChange("telemetry",e.target.value)} placeholder="All records" options={[{value:"complete",label:"Distance and fuel recorded"},{value:"missing",label:"Missing fuel details"}]} /></Field>
    </div>
    <details style={{marginTop:16}}>
      <summary style={{cursor:"pointer"}}>Amount, KM reading, distance, fuel quantity and mileage ranges</summary>
      <div className="fuel-report-filter-grid" style={{marginTop:16}}>
        {[["Amount","Amount (₹)"],["KmReading","KM reading"],["Distance","Distance (km)"],["Liters","Fuel (L)"],["Mileage","Mileage (km/L)"]].map(([key,label]) => <div key={key} className="stack">
          <Field label={`Minimum ${label}`}><Input type="number" min={0} step="any" value={values[`min${key}`]} onChange={(e) => onChange(`min${key}`,e.target.value)} /></Field>
          <Field label={`Maximum ${label}`}><Input type="number" min={0} step="any" value={values[`max${key}`]} onChange={(e) => onChange(`max${key}`,e.target.value)} /></Field>
        </div>)}
      </div>
    </details>
    <div style={{marginTop:16}}><Button variant="secondary" onClick={onReset} disabled={![...FUEL_FILTER_KEYS,"q"].some((key) => values[key])}>Clear fuel filters</Button></div>
  </Card>;
}
