import { useEffect, useRef, useState } from "react";
import { sendQuery } from "../api.js";
import ChatMessage from "./ChatMessage.jsx";

let nextId = 1;

export default function ChatWindow({ userId, userLabel }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const historyRef = useRef(null);

  useEffect(() => {
    historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function handleSend() {
    const question = input.trim();
    if (!question || sending || !userId) return;

    setMessages((prev) => [...prev, { id: nextId++, role: "user", text: question }]);
    setInput("");
    setSending(true);

    try {
      const response = await sendQuery(userId, question);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId++,
          role: "assistant",
          text: response.answer,
          citedSources: response.citedSources,
          clearance: response.clearance,
          traceId: response.traceId,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: nextId++, role: "assistant", text: err.message, isError: true },
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="panel chat-window">
      <h2>
        Ask Warden {userLabel ? <span className="muted">— as {userLabel}</span> : null}
      </h2>

      <div className="chat-history" ref={historyRef}>
        {messages.length === 0 && (
          <p className="muted chat-empty">
            Ask a question. Warden only answers from documents your current user is cleared to see.
          </p>
        )}

        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}

        {sending && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-message-bubble typing">Thinking…</div>
          </div>
        )}
      </div>

      <div className="chat-input-row">
        <textarea
          rows={1}
          placeholder="Ask about a customer, policy, or ticket…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!userId || sending}
        />
        <button onClick={handleSend} disabled={!userId || sending || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
