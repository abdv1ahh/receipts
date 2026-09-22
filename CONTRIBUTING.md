# Contributing

Issues and pull requests are welcome. Three rules are not negotiable, and each of them exists
because of something that already went wrong here.

---

## Before you push

```bash
make test          # the suite. Offline except the database-backed integrity tests
make test-js       # the cross-language guard on the sealed wire format. Runs on the HOST
make lint          # ruff. Zero errors is the standard
```

**`make test-js` is not optional and `make test` cannot replace it.** `receipts/chain.py` and
`receipts/verify.js` must produce byte-identical payloads forever, because the public record page
lets a visitor recompute the chain in their own browser — a JavaScript framing that disagrees by
one byte reports every intact record as broken, on the interaction the product is sold on. `make
test` runs inside the API image, which carries no node; the host that has node has no Python
dependencies. Neither place can run both languages, so both sides check one committed fixture
(`tests/fixtures/receipt_chain.json`). **Run both after touching either side.**

And run the browser check, not only the tests. A missing import has passed the whole suite and
thrown on the page.

---

## The three rules

### 1. The wire format is frozen

`chain.SEALED_FIELDS` is ten fields in a fixed order, framed as `name:byte-length:value` and joined
with newlines. **Adding a sealed field, reordering two, or changing how a timestamp renders would
invalidate every chain ever published.** A test pins the order.

Two details that look like style and are not:

* The fields are **length-prefixed rather than delimited**. A caller writes their own thesis, and
  with a plain separator they could type the separator into it and make two different calls
  serialise identically — a collision they control, and therefore a forged link.
* The length is in **bytes, not characters**. A four-byte emoji in a thesis is one character. Get
  this wrong and every record containing one reports as broken.

### 2. Never quote a rate or an expectancy without its interval

This project published `43.2% of 412, −1.18% expectancy` and concluded internally that the signal
does not work. The 95% interval on that mean is **[−2.93%, +0.57%]** and spans zero, so **no edge is
demonstrated in either direction** — the conclusion overclaimed, in the opposite direction from the
usual one. What *is* significant is the frequency (2.76 standard errors below a coin flip), and the
two statistics genuinely disagree because the wins are bigger than the losses.

`stats.mean_ci`, `proportion_z` and `sample_needed` are pure and tested. Use them. Below 25
resolved calls no rate is published at all, and that gate is not a hiding place: a gated caller
still shows every count and every call.

### 3. A verdict is permanent, so never seal an operational failure as one

The append-only trigger refuses to change a verdict once written — that is the product — and the
consequence is that `unscoreable` cannot be taken back. A symbol whose price feed is merely
**behind** is perfectly scoreable and our data is late. Sealing that case would be wrong an hour
later and uncorrectable forever.

So: **a call is sealed `unscoreable` if and only if no price series exists for its symbol.**
Nothing else may seal, and in particular no gap in our own benchmark, ever. A missing exit price
always leaves the call **open**, with a stored reason and the time it was last checked. A delisted
symbol staying open forever is visible, honest and correctable; a wrong verdict is none of those.

---

## Conventions

* **Module docstring first**, saying what the module is *for* and often which decision produced it.
* **Comments explain why, not what** — especially why an obvious approach was rejected. A rule
  without its measurement gets "simplified" away inside a year.
* `from __future__ import annotations`; modern `X | None` types.
* **Raw SQL, always parameterised.** Where SQL must be composed — a column list, an optional
  WHERE — use `psycopg.sql`, never an f-string. Ruff's `S608` enforces it.
* **Honest degradation over fabrication.** When a source is missing, the API returns a state and
  the UI says so. There is no fixture data presented as live anywhere, and there must never be.
* Naming: `snake_case` Python, `camelCase` JS, `kebab-case` CLI commands.
* Frontend: functional components, hooks only, `fetch` through `frontend/src/api.js`, plain CSS.

There is **no ORM**, **no migration framework** and **no state library**, and keeping it that way is
a decision rather than an oversight. `requirements.txt` is ten lines; adding to it needs an
argument in the pull request.

---

## Things that will cost you an hour

* **A frontend change needs `make web`** (0.3s) under `make dev`, or a full image rebuild.
* **`script-src 'self'` means an inline `<script>` is refused with nothing in the logs.** That is
  why the browser verifier is served as a file. A test asserts the page carries no inline script.
* **WebCrypto is undefined outside a secure context, and `localhost` hides it.** `crypto.subtle`
  exists on https and on localhost and nowhere else, so the verifier works perfectly in development
  and is dead on a plain-http LAN address — which is what a bare `docker compose up` with no proxy
  serves. `verify.js` checks and says which of the two things is wrong.
* **A grid or flex track written `1fr` is `min-width: auto`** and will not shrink below its
  content. Write `minmax(0, 1fr)`. Check any UI change at 375px, not just at your window width.
* **A media query adds no specificity**, so narrow-screen overrides must sit at the end of
  `styles.css`. There is a marked block there for them.
* **A key in `.env` does not reach the container.** `docker-compose.yml` enumerates every variable
  explicitly, so a key added to `.env` alone is silently absent from `api` and `worker`. Add it in
  both services, then `docker compose up -d api worker`.
* **Every migration must insert its own `schema_migrations` row**; the runner does not. And a
  **fresh** install takes `migrations/baseline/001_baseline.sql` instead of the ordered files, so a
  new migration needs the baseline updated too — `tests/test_migrations.py` fails if the two paths
  stop producing the same schema.

---

## Documentation

Reconcile the docs in the same change that changed the behaviour. A wrong command in a README is
worse than no command, and `docs/known_gaps.md` names the exact sentence the product says about
each gap so the two cannot drift.

If you find a documented command that does not work, fixing the document is part of the change that
discovered it.

---

**Nothing in this repository is investment advice.**
