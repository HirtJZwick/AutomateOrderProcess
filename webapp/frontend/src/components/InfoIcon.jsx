import { useState } from "react";

export default function InfoIcon({ text }) {
  const [hovered, setHovered] = useState(false);
  const [open, setOpen] = useState(false);
  const visible = hovered || open;

  function toggle(e) {
    e.preventDefault();
    e.stopPropagation();
    setOpen((current) => !current);
  }

  return (
    <span
      className="info-wrap"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className="info-icon"
        aria-label="Show shipping date reason"
        aria-expanded={visible}
        onClick={toggle}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        i
      </button>
      {visible && (
        <span className="info-tooltip" role="tooltip">
          {text}
        </span>
      )}
    </span>
  );
}
