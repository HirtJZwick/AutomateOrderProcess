import { useEffect, useState } from "react";
import { api } from "./api";
import OrderCard from "./components/OrderCard";
import OrderDetail from "./components/OrderDetail";

export default function App() {
  const [orders, setOrders] = useState([]);
  const [rootFolder, setRootFolder] = useState("");
  const [rootExists, setRootExists] = useState(false);
  const [savedFolder, setSavedFolder] = useState("");
  const [selected, setSelected] = useState(() => {
    return new URLSearchParams(window.location.search).get("order");
  });
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  async function loadOrders() {
    try {
      const data = await api.listOrders();
      setOrders(data.orders);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    api
      .getConfig()
      .then((c) => {
        setRootFolder(c.root_folder || "");
        setSavedFolder(c.root_folder || "");
        setRootExists(!!c.root_exists);
      })
      .catch((e) => setError(e.message));
    loadOrders();
  }, []);

  const dirty = rootFolder.trim() !== savedFolder.trim();

  async function handleSaveFolder() {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const res = await api.setRootFolder(rootFolder.trim());
      setSavedFolder(res.root_folder);
      setRootFolder(res.root_folder);
      setRootExists(!!res.root_exists);
      setMessage(
        res.root_exists
          ? "Scan folder saved."
          : "Saved, but that folder was not found on disk — check the path."
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleScan() {
    setScanning(true);
    setMessage(null);
    setError(null);
    try {
      const res = await api.scan();
      setMessage(
        `Scan complete — ${res.ingested_count} order(s) loaded from ${res.folders_found} folder(s) found.`
      );
      await loadOrders();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }

  return (
    <>
      <header className="app-header">
        <div>
          <h1>
            ZwickRoell <span className="brand-dot">Order Tracker</span>
          </h1>
          <div className="sub">Order overview before customer conversations</div>
        </div>
        <button className="btn" onClick={handleScan} disabled={scanning || !rootExists}>
          {scanning ? "Scanning…" : "Scan orders"}
        </button>
      </header>

      <div className="settings-bar">
        <label htmlFor="root" className="settings-label">
          Scan folder
        </label>
        <input
          id="root"
          className="folder-input"
          type="text"
          value={rootFolder}
          placeholder="C:\\path\\to\\folder containing the order folders"
          spellCheck={false}
          onChange={(e) => setRootFolder(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && dirty && handleSaveFolder()}
        />
        <span
          className={`folder-status ${rootExists ? "ok" : "bad"}`}
          title={rootExists ? "Folder found" : "Folder not found"}
        >
          {rootExists ? "● found" : "● not found"}
        </span>
        <button className="btn secondary" onClick={handleSaveFolder} disabled={saving || !dirty}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      {message && <div className="toast">{message}</div>}
      {error && <div className="toast error">{error}</div>}

      <div className="container">
        {orders.length === 0 ? (
          <div className="empty">
            <h2>No orders yet</h2>
            <p>Set the scan folder above, then click “Scan orders” to load orders.</p>
          </div>
        ) : (
          <div className="grid">
            {orders.map((o) => (
              <OrderCard key={o.dossier_no} order={o} onOpen={setSelected} />
            ))}
          </div>
        )}
      </div>

      {selected && <OrderDetail dossier={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
