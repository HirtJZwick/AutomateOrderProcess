import { stageColor } from "../colors";

// Horizontal stage band: New -> Order Confirmed -> Packed -> Shipped.
// Steps up to and including the current stage are colored.
export default function StageBand({ stage }) {
  const stages = stage?.stages || [];
  const current = stage?.index ?? -1;
  return (
    <div className="stage-band">
      {stages.map((name, i) => {
        const active = i <= current;
        return (
          <div
            key={name}
            className={`stage-step${active ? " active" : ""}`}
            style={active ? { background: stageColor(name) } : undefined}
            title={name}
          >
            {name}
          </div>
        );
      })}
    </div>
  );
}
