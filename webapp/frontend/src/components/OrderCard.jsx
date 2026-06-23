import StageBand from "./StageBand";
import CompletenessBar from "./CompletenessBar";
import { stageColor } from "../colors";

function Meta({ label, value }) {
  return (
    <div className="meta-item">
      <div className="label">{label}</div>
      <div className="value">{value || "—"}</div>
    </div>
  );
}

// Extract just the contact name from a packed contact string.
function contactName(raw) {
  if (!raw) return "";
  return raw.split("/")[0].trim();
}

export default function OrderCard({ order, onOpen }) {
  const stageName = order.stage?.name || "New";
  return (
    <div
      className="card"
      style={{ borderLeftColor: stageColor(stageName) }}
      onClick={() => onOpen(order.dossier_no)}
    >
      <div className="card-top">
        <div>
          <div className="card-customer">{order.customer_name || "Unknown customer"}</div>
          <div className="card-dossier">
            Dossier {order.dossier_no} &middot; {order.order_id || "—"}
          </div>
        </div>
        <span className="stage-pill" style={{ background: stageColor(stageName) }}>
          {stageName}
        </span>
      </div>

      <div className="card-meta">
        <Meta label="Machine" value={order.machine_type} />
        <Meta label="Industry" value={order.industry} />
        <Meta label="Order date" value={order.order_date} />
        <Meta label="OC received" value={order.received_oc_from_zrx} />
        <Meta label="Customer contact" value={contactName(order.technical_contact) || order.shipping_contact} />
        <Meta label="Sales mgr (RSM)" value={order.rsm} />
      </div>

      <StageBand stage={order.stage} />
      <CompletenessBar completeness={order.completeness} />
    </div>
  );
}
