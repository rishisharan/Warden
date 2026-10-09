export default function ChatMessage({ message }) {
  const { role, text, citedSources, clearance, traceId, isError } = message;

  return (
    <div className={`chat-message chat-message-${role}${isError ? " chat-message-error" : ""}`}>
      <div className="chat-message-bubble">
        <p>{text}</p>

        {citedSources && citedSources.length > 0 && (
          <div className="cited-sources">
            <span className="cited-sources-label">Sources</span>
            <ul>
              {citedSources.map((s, i) => (
                <li key={i}>
                  {s.sourceFile}
                  <span className="source-meta"> ({s.sourceType}, {s.accessLevel})</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(clearance || traceId) && (
          <div className="chat-message-meta">
            {clearance && <span>clearance: {clearance}</span>}
            {traceId && <span>traceId: {traceId}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
