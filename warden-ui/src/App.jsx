import { useEffect, useState } from "react";
import { fetchUsers, login, logout } from "./api.js";
import UploadPanel from "./components/UploadPanel.jsx";
import ChatWindow from "./components/ChatWindow.jsx";

export default function App() {
  const [user, setUser] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchUsers()
      .then(([current]) => setUser(current ?? null))
      .catch((failure) => setError(failure.message))
      .finally(() => setBusy(false));
  }, []);

  async function signIn(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError("");
    try {
      await login(fields.get("username"), fields.get("password"));
      const [current] = await fetchUsers();
      setUser(current ?? null);
      form.reset();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    setBusy(true);
    setError("");
    try {
      await logout();
      setUser(null);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Warden</h1>
        <p className="tagline">
          Permission-aware knowledge retrieval for support teams.
        </p>
      </header>

      <main className={user ? "app-main" : "app-main app-main-signed-out"}>
        <aside className="app-sidebar">
          {user ? (
            <section>
              <p>{user.displayName} ({user.role})</p>
              <button type="button" onClick={signOut} disabled={busy}>Sign out</button>
            </section>
          ) : (
            <form className="panel login-form" onSubmit={signIn}>
              <label>
                Username
                <input name="username" autoComplete="username" required />
              </label>
              <label>
                Password
                <input name="password" type="password" autoComplete="current-password" required />
              </label>
              {error && <p className="login-error" role="alert">{error}</p>}
              <button type="submit" disabled={busy}>Sign in</button>
            </form>
          )}
          {user && error && <p role="alert">{error}</p>}
          {user?.clearance === "MANAGER" && <UploadPanel />}
        </aside>

        {user && <ChatWindow key={user.userId} userId={user.userId} userLabel={user.displayName} />}
      </main>
    </div>
  );
}
