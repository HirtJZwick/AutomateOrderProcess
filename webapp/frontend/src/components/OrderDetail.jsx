import { useEffect, useState } from "react";
import { api } from "../api";
import StageBand from "./StageBand";
import CompletenessBar from "./CompletenessBar";
import { stageColor } from "../colors";

const MILESTONE_PHASES = ["Pre-FAT", "FAT", "Logistics", "Install", "Qualification"];

function Field({ label, value, full }) {
  return (
    <div className={`field${full ? " full" : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value || "—"}</div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="section">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export default function OrderDetail({ dossier, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    api
      .getOrder(dossier)
      .then((d) => active && setData(d))
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [dossier]);

  function stop(e) {
    e.stopPropagation();
  }

  const o = data?.order || {};
  const stageName = data?.stage?.name || "New";

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={stop}>
        <div className="drawer-head">
          <div>
            <h2>{o.customer_name || dossier}</h2>
            <div className="card-dossier">
              Dossier {dossier} &middot; {o.order_id || "—"}
            </div>
          </div>
          <button className="close-x" onClick={onClose}>
            &times;
          </button>
        </div>

        {error && <div className="toast error" style={{ margin: "16px 0" }}>{error}</div>}
        {!data && !error && <p style={{ color: "var(--muted)" }}>Loading…</p>}

        {data && (
          <>
            <div style={{ marginTop: 14 }}>
              <span className="stage-pill" style={{ background: stageColor(stageName) }}>
                {stageName}
              </span>
            </div>
            <StageBand stage={data.stage} />
            <CompletenessBar completeness={data.completeness} />

            <Section title="Overview">
              <div className="field-grid">
                <Field label="Machine type" value={o.machine_type} />
                <Field label="Industry" value={o.industry} />
                <Field label="Order date" value={o.order_date} />
                <Field label="Shipping date" value={o.shipping_date} />
                <Field label="PO received on" value={o.po_received_on} />
                <Field label="Purchase order no." value={o.oc_purchase_order_no} />
                <Field label="Quotation no." value={o.oc_quotation_no} />
                <Field label="Install location" value={o.ship_to_address} full />
              </div>
            </Section>

            <Section title="Contacts">
              <div className="field-grid">
                <Field label="Customer contact" value={o.technical_contact || o.shipping_contact} full />
                <Field label="Regional Sales Manager" value={o.rsm} />
                <Field label="RSM email" value={o.rsm_email} />
                <Field label="Logistics coordinator" value={o.logistics_coordinator} />
                <Field label="Logistics phone" value={o.logistics_coordinator_phone} />
                <Field label="Logistics email" value={o.logistics_coordinator_email} />
              </div>
            </Section>

            <Section title="Order processing timeline">
              <div className="field-grid">
                <Field label="PO sent to ZRX" value={o.send_po_to_zrx} />
                <Field label="Order acknowledgement" value={o.send_order_acknowledgement} />
                <Field label="OC received from ZRX" value={o.received_oc_from_zrx} />
                <Field label="OC sent to customer" value={o.oc_sent_to_customer} />
                <Field label="Packing details from ZRX" value={o.packing_details_from_zrx} />
                <Field label="Collection / tracking" value={o.collection_order_to_forwarder} />
                <Field label="Customer informed (CIA)" value={o.information_customer_cia} />
                <Field label="Invoice received from ZRX" value={o.invoice_received_from_zrx} />
              </div>
            </Section>

            <Section title="Service">
              <div className="field-grid">
                <Field label="Installation required (hrs)" value={o.installation_required_hours} />
                <Field label="Technician" value={o.technician} />
                <Field label="Special cal gear" value={o.special_cal_gear_required} />
                <Field label="Service activity by" value={o.service_activity_done_by} />
              </div>
            </Section>

            <Section title={`Documents (${data.documents.length})`}>
              <ul className="doc-list">
                {data.documents.map((d) => (
                  <li className="doc-row" key={d.rel_path}>
                    <span className="doc-cat">{d.category}</span>
                    <span>{d.file_name}</span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="FAT plan phases (reference)">
              <div className="phases">
                {MILESTONE_PHASES.map((p) => (
                  <span className="phase-tag" key={p}>
                    {p}
                  </span>
                ))}
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
