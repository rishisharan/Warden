import { useEffect, useState } from "react";
import { fetchUsers } from "./api.js";
import UserSwitcher from "./components/UserSwitcher.jsx";
import UploadPanel from "./components/UploadPanel.jsx";
import ChatWindow from "./components/ChatWindow.jsx";

export default function App() {
  const [users, setUsers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState(null);

  useEffect(() => {
    fetchUsers()
      .then((data) => {
        setUsers(data);
        if (data.length > 0) setSelectedUserId(data[0].userId);
      })
      .catch((err) =>
        setUsersError(err.message || "Could not reach warden-api. Is it running on :8082?")
      )
      .finally(() => setUsersLoading(false));
  }, []);

  const selectedUser = users.find((u) => u.userId === selectedUserId);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Warden</h1>
        <p className="tagline">
          Permission-aware knowledge retrieval — the model only ever sees what your clearance
          already permits.
        </p>
      </header>

      <main className="app-main">
        <aside className="app-sidebar">
          <UserSwitcher
            users={users}
            selectedUserId={selectedUserId}
            onChange={setSelectedUserId}
            loading={usersLoading}
            error={usersError}
          />
          <UploadPanel />
        </aside>

        <ChatWindow userId={selectedUserId} userLabel={selectedUser?.displayName} />
      </main>
    </div>
  );
}
