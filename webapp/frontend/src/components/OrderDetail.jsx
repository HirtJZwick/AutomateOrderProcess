import { useEffect, useState } from "react";
import { api } from "../api";
import StageBand from "./StageBand";
import CompletenessBar from "./CompletenessBar";
import { stageColor } from "../colors";

const MILESTONE_PHASES = ["Pre-FAT", "FAT", "Logistics", "Install", "Qualification"];

function EditField({ label, fieldKey, value, onChange, full, multiline }) {
  return (
    <div className={`field${full ? " full" : ""}`}>
      <div className="label">{label}</div>
      {multiline ? (
        <textarea
          className="edit-textarea"
          value={value}
          rows={3}
          onChange={(e) => onChange(fieldKey, e.target.value)}
        />
      ) : (
        <input
          className="edit-input"
          type="text"
          value={value}
          onChange={(e) => onChange(fieldKey, e.target.value)}
        />
      )}
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

export default function OrderDetail({ dossier, onClose, onOrderUpdated }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [actionMessage, setActionMessage] = useState(null);

  useEffect(() => {
    let active = true;
    setEdits({});
    setActionError(null);
    setActionMessage(null);
    api
      .getOrder(dossier)
      .then((d) => active && setData(d))
      .catch((e) => active && setError(e.message));
    return () => { active = false; };
  }, [dossier]);

  function stop(e) { e.stopPropagation(); }

  function handleChange(fieldKey, value) {
    setEdits((prev) => ({ ...prev, [fieldKey]: value }));
    setActionError(null);
    setActionMessage(null);
  }

  // Returns pending edit value if the user has changed this field,
  // otherwise falls back to the server value.
  function fieldValue(key) {
    return Object.prototype.hasOwnProperty.call(edits, key)
      ? edits[key]
      : (data?.order[key] ?? "");
  }

  const isDirty = Object.keys(edits).length > 0;

  async function handleSave() {
    setSaving(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const res = await api.updateOrder(dossier, edits);
      setData(res);
      setEdits({});
      setActionMessage("Changes saved.");
      onOrderUpdated?.();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const res = await api.refreshOrder(dossier);
      setData(res);
      setEdits({});
      setActionMessage(`Refreshed — ${res.documents.length} document(s) found.`);
      onOrderUpdated?.();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setRefreshing(false);
    }
  }

  const o = data?.order || {};
  const stageName = data?.stage?.name || "New";

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={stop}>
        <div className="drawer-head">
          <div>
            <h2>{fieldValue("customer_name") || dossier}</h2>
            <div className="card-dossier">
              Dossier {dossier} &middot; {o.order_id || "—"}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              className="btn secondary btn-sm"
              onClick={handleRefresh}
              disabled={refreshing}
              title="Re-scan the order folder for new documents and fill any empty fields"
            >
              {refreshing ? "Refreshing…" : "↻ Refresh"}
            </button>
            <button className="close-x" onClick={onClose}>&times;</button>
          </div>
        </div>

        {error && <div className="toast error" style={{ margin: "16px 0" }}>{error}</div>}
        {actionError && <div className="toast error" style={{ margin: "12px 0 0" }}>{actionError}</div>}
        {actionMessage && <div className="toast" style={{ margin: "12px 0 0" }}>{actionMessage}</div>}
        {!data && !error && <p style={{ color: "var(--muted)" }}>Loading…</p>}

        {data && (
          <>
            <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 8 }}>
              <span className="stage-pill" style={{ background: stageColor(stageName) }}>
                {stageName}
              </span>
              {o.cancelled === "1" && (
                <span className="cancelled-pill">Cancelled</span>
              )}
            </div>
            <StageBand stage={data.stage} />
            <CompletenessBar completeness={data.completeness} />

            <Section title="Overview">
              <div className="field-grid">
                <EditField label="Machine type"       fieldKey="machine_type"        value={fieldValue("machine_type")}        onChange={handleChange} />
                <EditField label="Industry"           fieldKey="industry"            value={fieldValue("industry")}            onChange={handleChange} />
                <EditField label="Order date"         fieldKey="order_date"          value={fieldValue("order_date")}          onChange={handleChange} />
                <EditField label="Shipping date"      fieldKey="shipping_date"       value={fieldValue("shipping_date")}       onChange={handleChange} />
                <EditField label="PO received on"     fieldKey="po_received_on"      value={fieldValue("po_received_on")}      onChange={handleChange} />
                <EditField label="Purchase order no." fieldKey="oc_purchase_order_no" value={fieldValue("oc_purchase_order_no")} onChange={handleChange} />
                <EditField label="Quotation no."      fieldKey="oc_quotation_no"     value={fieldValue("oc_quotation_no")}     onChange={handleChange} />
                <EditField label="Install location"   fieldKey="ship_to_address"     value={fieldValue("ship_to_address")}     onChange={handleChange} full multiline />
              </div>
            </Section>

            <Section title="Contacts">
              <div className="field-grid">
                <EditField label="Technical contact"     fieldKey="technical_contact"          value={fieldValue("technical_contact")}          onChange={handleChange} full />
                <EditField label="Shipping contact"      fieldKey="shipping_contact"           value={fieldValue("shipping_contact")}           onChange={handleChange} full />
                <EditField label="Regional Sales Manager" fieldKey="rsm"                       value={fieldValue("rsm")}                        onChange={handleChange} />
                <EditField label="RSM email"             fieldKey="rsm_email"                  value={fieldValue("rsm_email")}                  onChange={handleChange} />
                <EditField label="Logistics coordinator" fieldKey="logistics_coordinator"      value={fieldValue("logistics_coordinator")}      onChange={handleChange} />
                <EditField label="Logistics phone"       fieldKey="logistics_coordinator_phone" value={fieldValue("logistics_coordinator_phone")} onChange={handleChange} />
                <EditField label="Logistics email"       fieldKey="logistics_coordinator_email" value={fieldValue("logistics_coordinator_email")} onChange={handleChange} />
              </div>
            </Section>

            <Section title="Order processing timeline">
              <div className="field-grid">
                <EditField label="PO sent to ZRX"          fieldKey="send_po_to_zrx"              value={fieldValue("send_po_to_zrx")}              onChange={handleChange} />
                <EditField label="Order acknowledgement"   fieldKey="send_order_acknowledgement"  value={fieldValue("send_order_acknowledgement")}  onChange={handleChange} />
                <EditField label="OC received from ZRX"    fieldKey="received_oc_from_zrx"        value={fieldValue("received_oc_from_zrx")}        onChange={handleChange} />
                <EditField label="OC sent to customer"     fieldKey="oc_sent_to_customer"         value={fieldValue("oc_sent_to_customer")}         onChange={handleChange} />
                <EditField label="Packing details from ZRX" fieldKey="packing_details_from_zrx"  value={fieldValue("packing_details_from_zrx")}   onChange={handleChange} />
                <EditField label="Collection / tracking"   fieldKey="collection_order_to_forwarder" value={fieldValue("collection_order_to_forwarder")} onChange={handleChange} />
                <EditField label="Customer informed (CIA)" fieldKey="information_customer_cia"    value={fieldValue("information_customer_cia")}    onChange={handleChange} />
                <EditField label="Invoice received from ZRX" fieldKey="invoice_received_from_zrx" value={fieldValue("invoice_received_from_zrx")}  onChange={handleChange} />
              </div>
            </Section>

            <Section title="Service">
              <div className="field-grid">
                <EditField label="Installation required (hrs)" fieldKey="installation_required_hours" value={fieldValue("installation_required_hours")} onChange={handleChange} />
                <EditField label="Technician"           fieldKey="technician"               value={fieldValue("technician")}               onChange={handleChange} />
                <EditField label="Special cal gear"     fieldKey="special_cal_gear_required" value={fieldValue("special_cal_gear_required")} onChange={handleChange} />
                <EditField label="Service activity by"  fieldKey="service_activity_done_by" value={fieldValue("service_activity_done_by")} onChange={handleChange} />
              </div>
            </Section>

            {isDirty && (
              <div className="drawer-save-bar">
                <span className="save-hint">Unsaved changes</span>
                <button className="btn btn-sm" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </button>
              </div>
            )}

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
                  <span className="phase-tag" key={p}>{p}</span>
                ))}
              </div>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
