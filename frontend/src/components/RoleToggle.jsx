// customer (public only) / staff (public + private). Switching role starts a fresh conversation
// (see App) — the whole point is to show RQ2 access isolation live: staff sees private content a
// customer never does.
const ROLES = ['customer', 'staff']

export default function RoleToggle({ value, onChange }) {
  return (
    <div className="field">
      <span>Role</span>
      <div className="toggle">
        {ROLES.map((r) => (
          <button
            key={r}
            type="button"
            className={value === r ? 'active' : ''}
            onClick={() => onChange(r)}
          >
            {r}
          </button>
        ))}
      </div>
    </div>
  )
}
