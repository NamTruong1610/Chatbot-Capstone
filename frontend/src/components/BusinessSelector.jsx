// Business dropdown, populated from GET /api/domains. Non-ready businesses are shown with their
// status appended (e.g. "CutPro — crawling") so you can watch a newly-added one become selectable.
export default function BusinessSelector({ domains, value, onChange }) {
  return (
    <label className="field">
      <span>Business</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {domains.length === 0 && <option value="">(none loaded)</option>}
        {domains.map((d) => (
          <option key={d.domain_id} value={d.domain_id}>
            {d.display_name}
            {d.status !== 'ready' ? ` — ${d.status}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
