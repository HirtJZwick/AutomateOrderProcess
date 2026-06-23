import { levelColor } from "../colors";

// Completeness/progress bar showing how much info we have for the order.
export default function CompletenessBar({ completeness }) {
  const c = completeness || { percent: 0, level: "missing", present: 0, total: 0 };
  return (
    <div className="completeness">
      <div className="bar-head">
        <span>Information completeness</span>
        <span>
          {c.percent}% &middot; {c.present}/{c.total} fields
        </span>
      </div>
      <div className="bar">
        <span style={{ width: `${c.percent}%`, background: levelColor(c.level) }} />
      </div>
    </div>
  );
}
