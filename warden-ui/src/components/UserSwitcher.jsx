export default function UserSwitcher({ users, selectedUserId, onChange, loading, error }) {
  const selected = users.find((u) => u.userId === selectedUserId);

  return (
    <div className="panel">
      <h2>Signed in as</h2>

      {loading && <p className="muted">Loading users…</p>}
      {error && <p className="error-text">{error}</p>}

      {!loading && !error && (
        <>
          <select value={selectedUserId} onChange={(e) => onChange(e.target.value)}>
            {users.map((u) => (
              <option key={u.userId} value={u.userId}>
                {u.displayName} ({u.role})
              </option>
            ))}
          </select>

          {selected && (
            <span className={`clearance-badge clearance-${selected.clearance.toLowerCase()}`}>
              {selected.clearance} clearance
            </span>
          )}
        </>
      )}
    </div>
  );
}
