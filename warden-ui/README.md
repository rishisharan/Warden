# Warden UI

React (Vite) front end for Warden. Two things, one page:

- **Upload a document** - pick a `.txt`/`.md` file, pick `public` or
  `manager`, upload. That access level is written onto every chunk the
  file produces in Chroma (via `warden-api`'s `POST /api/documents`,
  which forwards to the Python retrieval service's `/ingest`).
- **Chat** - pick which fake user you're signed in as (from
  `GET /api/users`), type a question, hit Enter. Calls
  `POST /api/query` and renders the answer plus its cited sources. The
  user you're signed in as controls what the backend is allowed to
  retrieve for you - switch users and ask the same question to see the
  difference.

## Run it

```
npm install
npm run dev
```

Opens on `http://localhost:5173`. Needs `warden-api` running on
`http://localhost:8082` (see `../README.md`) - CORS for this origin is
already allowed there (`CorsConfig.java`).

To point at a different `warden-api` URL, copy `.env.example` to
`.env.local` and set `VITE_API_BASE_URL`.

## Notes

- No build step is required to try it - `npm run dev` is enough for the
  demo. `npm run build` produces a static `dist/` if you want to host it
  somewhere.
- There's no real login: the "signed in as" dropdown and the upload's
  access-level picker are both self-declared, same as the rest of this
  MVP (see "Known MVP simplifications" in `../README.md`).
