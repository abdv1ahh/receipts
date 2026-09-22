// The display name, in ONE place.
//
// `tradeos` remains the internal name — the Python package, the database tables and the container
// names all still use it, and renaming those for branding is explicitly out of bounds: the
// append-only triggers and `schema_migrations` are matched BY NAME, and a half-finished rename
// against a live database is how a sealed table loses its trigger.
//
// What a READER sees is this constant. It was previously a `const BRAND` inside App.jsx while
// fourteen other user-facing strings across nine files spelled the name out by hand, so a rebrand
// reached only the navigation bar: the landing page, the disclaimers and the pricing copy all
// still said the old one. That is the failure this file exists to prevent, and it is why there are
// exactly two homes for the name — here, and `config.brand_name()` on the server.
//
// The backend has the matching value in `config.brand_name()` (env `BRAND_NAME`). These two are
// deliberately not wired to each other: doing so would mean blocking first paint on a config
// request to render a word that changes about once in a product's life.
// Receipts: what the thing is, and the only one of its three past names a stranger can guess the
// meaning of. A self-hoster puts their own here, or sets BRAND_NAME and leaves this alone.
export const BRAND = "Receipts";
