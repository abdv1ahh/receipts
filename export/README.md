# Exported records

Every sealed call by these callers, with the two hashes that chain them, in the exact bytes they
were hashed from. No server is involved in checking them:

```
node check.mjs
```

| caller | calls | chain head |
|---|---:|---|
| `@convergence-v3` | 323 | `c9f480e0a79a28c7` |\n| `@convergence-v4` | 150 | `24df0daed4f23ccd` |

## These are a SEALED BACKTEST, not foresight

**Every call in this export was imported from an already-scored ledger and sealed after its
outcome was known.** They are not predictions that were published in advance and then resolved.
They exist to demonstrate the machinery — the chaining, the scoring, the append-only trigger, the
browser check — over a real sample rather than a toy one, and `MANIFEST.json` marks each of them
`sealed_after_the_outcome_was_known: true`.

A call published through the product is sealed at PUBLICATION, before the outcome exists. That is
the whole claim, and it is not the claim these records support.

## The numbers, which are bad

Pooled across both: **43.2% right on 412 resolved calls**, which is 2.76 standard errors below a
coin flip. Average excess return per call against SPY: **−1.18%**, with a 95% interval of
**[−2.93%, +0.57%]** that spans zero — so on this sample no edge is shown in either direction, and
the frequency and the return genuinely disagree. At the measured dispersion it would take **1,268**
resolved calls to detect a 1% per-call edge.

This is not presented as a positive result and never should be.

## What `check.mjs` proves, and what it does not

It proves the CALLER has not edited, deleted, reordered or backdated anything: every hash is
recomputed from the fields in these files, and one changed character breaks every link after it.
It runs the tamper test on itself so you can watch it say no.

It does NOT prove the operator did not rewrite the whole chain and recompute it. They held every
field. Closing that needs an anchor outside their control — publishing the chain head somewhere
they cannot revise — and that is not built. This is not a blockchain.

## What is in each file

`fields` is the sealed field list, in the frozen order. `framing` states how to turn a link's
values into the bytes that were hashed, so a checker written in any language needs nothing from
this repository. `links[].values` are already rendered to text, because two of the fields are
timestamps whose sealed spelling carries microseconds and a trailing `Z` that a JavaScript `Date`
round trip would drop.

Nothing here is investment advice.
