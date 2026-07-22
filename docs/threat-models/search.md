# Threat model — unified search (Slice J)

Scope: `tradeos/search.py` and `/api/search`. Read-only search across issuers, institutions, insiders,
the intelligence library, and public traders.

## Assets
- No private data may leak through search.
- Search input must not become an injection or match-all vector.

## Attacks and the design that stops them
1. **Private-data exposure.** Only **public** handles are searchable (users with a NULL handle, and all
   emails/user-ids, are excluded); issuer/institution/insider entities are public SEC records; no private
   trades, watchlists, portfolios, or billing are searchable.
2. **LIKE-wildcard injection / match-all.** `clean_query` escapes `%`, `_`, and `\` (so a user '%' is a
   literal, not a match-all) and trims + caps length to 64. All queries are parameterized (no SQL
   injection); the symbol query fetches prefix matches separately so ranking can't be gamed into a dump.
3. **Enumeration / scraping.** Each category is capped (6); results are the same public records already
   reachable on their own pages. A shared edge rate limiter is the named scale control.

## Residual / deferred (named)
- Relevance ranking beyond symbol-prefix + name-substring (popularity / market-cap weighting) is a later
  enhancement; a shared edge rate limiter replaces the per-process one at scale.
