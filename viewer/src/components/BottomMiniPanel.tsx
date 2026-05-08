import './Diff.css';

export interface MiniPanelItem {
  label: string;
  value: string;
}

interface BottomMiniPanelProps {
  items: MiniPanelItem[];
}

/**
 * Small stats bar for the diff page.
 * Desktop: fixed overlay at bottom-right.
 * Mobile: sticky bar above the page edge while navigation lives in a drawer.
 * Intentional scope note: this is not the old 30vh mobile navigation panel.
 * AppShell owns navigation/drawer behavior; this component only reports local
 * diff stats so it remains compact and non-modal.
 */
export default function BottomMiniPanel({ items }: BottomMiniPanelProps) {
  if (items.length === 0) return null;

  return (
    <div className="mini-panel" role="status" aria-live="polite">
      {items.map((item) => (
        <span key={item.label} className="mini-panel__item">
          <span className="mini-panel__label">{item.label}</span>
          <span className="mini-panel__value">{item.value}</span>
        </span>
      ))}
    </div>
  );
}
