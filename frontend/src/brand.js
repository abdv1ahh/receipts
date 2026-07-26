// The display name, in ONE place.
//
// `TradeOSS` remains the internal codename — the Python package, the database tables and the
// container names all still use it, and renaming those for branding is explicitly out of bounds.
// What a READER sees is this constant. It was previously a `const BRAND` inside App.jsx while
// fourteen other user-facing strings across nine files spelled out "TradeOSS" by hand, so the
// rebrand was only ever applied to the navigation bar: the landing page, the disclaimers, the
// assistant's model label and the pricing copy all still said the old name.
//
// The backend has the matching value in `config.brand_name()` (env `BRAND_NAME`). These two are
// deliberately not wired to each other: doing so would mean blocking first paint on a config
// request to render a word that changes about once in a product's life.
export const BRAND = "Rhumb";
