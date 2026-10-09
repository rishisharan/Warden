import { useRef, useState } from "react";
import { uploadDocument } from "../api.js";

// Access level is chosen here, at upload time - not inferred, not fixed
// up later. Whatever the uploader picks is exactly what gets written as
// metadata on every chunk in Chroma, and that metadata is the only thing
// /search's filter ever checks. Getting this control right here is the
// whole permission model.
export default function UploadPanel() {
  const fileInputRef = useRef(null);
  const [accessLevel, setAccessLevel] = useState("public");
  const [status, setStatus] = useState(null); // { type: "success" | "error", message }
  const [busy, setBusy] = useState(false);

  async function handleUpload(e) {
    e.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setStatus({ type: "error", message: "Choose a .txt or .md file first." });
      return;
    }

    setBusy(true);
    setStatus(null);
    try {
      const result = await uploadDocument(file, accessLevel);
      setStatus({
        type: "success",
        message: `Stored ${result.chunksStored} chunk${result.chunksStored === 1 ? "" : "s"} from "${result.filename}" as ${result.accessLevel}.`,
      });
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setStatus({ type: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h2>Upload a document</h2>
      <form onSubmit={handleUpload} className="upload-form">
        <input ref={fileInputRef} type="file" accept=".txt,.md" disabled={busy} />

        <fieldset className="access-level-choice" disabled={busy}>
          <legend>Who can see this?</legend>
          <label>
            <input
              type="radio"
              name="accessLevel"
              value="public"
              checked={accessLevel === "public"}
              onChange={(e) => setAccessLevel(e.target.value)}
            />
            Public — everyone
          </label>
          <label>
            <input
              type="radio"
              name="accessLevel"
              value="manager"
              checked={accessLevel === "manager"}
              onChange={(e) => setAccessLevel(e.target.value)}
            />
            Manager only
          </label>
        </fieldset>

        <button type="submit" disabled={busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>

      {status && (
        <p className={status.type === "error" ? "error-text" : "success-text"}>{status.message}</p>
      )}

      <p className="hint">
        .txt or .md, up to 2 MB. The access level above is stored on every chunk this document
        produces — there's no separate "classify later" step.
      </p>
    </div>
  );
}
