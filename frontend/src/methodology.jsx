// How a call is scored, rendered entirely from /api/receipts/methodology.
//
// Nothing on this page is typed here. A methodology page written by hand drifts from the code the
// first time a constant moves, and the drift is invisible: the page still reads correctly, it is
// just no longer true. Every number and every rule below is read from the same constants the
// scorer uses, so the page cannot describe a system that does not exist.
//
// The section that matters most is the last one. The chain is tamper evident against the CALLER
// and not against US, and saying so plainly is worth more than the overclaim would be. An investor
// who catches an overclaim discounts everything else on the page, including the true parts.
import { useEffect, useState } from "react";
import { fetchReceiptsMethodology } from "./api";
import { Icon } from "./icons.jsx";
import { LoadError } from "./shell.jsx";
import { Disclaimer } from "./receiptsui.jsx";

export function ReceiptsMethodologyView() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setData(null);
    setFailed(false);
    fetchReceiptsMethodology().then(setData).catch(() => setFailed(true));
  };
  useEffect(load, []);

  if (failed) return <LoadError what="the methodology" onRetry={load} />;
  if (!data) return <div className="rc-skel"><div className="skel" style={{ width: 340, height: 44 }} /></div>;

  return (
    <div className="mt-page">
      <header className="mt-head">
        <h1 className="rc-name">How a call is scored</h1>
        <p className="rc-lede">
          Every rule here is read from the code that applies it, so this page cannot describe a
          system that is not running.
        </p>
      </header>

      <section className="mt-section">
        <h2 className="rc-h2">Entry and exit</h2>
        <p>{data.entry}</p>
        <p>{data.exit}</p>
        <p>{data.benchmark}</p>
      </section>

      <section className="mt-section">
        <h2 className="rc-h2">The noise floor</h2>
        <p>{data.noise_floor_text}</p>
      </section>

      <section className="mt-section">
        <h2 className="rc-h2">The four verdicts</h2>
        <dl className="mt-verdicts">
          {data.verdicts.map((v) => (
            <div key={v.key}>
              <dt className={`rc-chip rc-${v.key === "inconclusive" ? "incon" : v.key === "unscoreable" ? "unsc" : v.key}`}>
                {v.key}
              </dt>
              <dd>{v.means}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mt-section">
        <h2 className="rc-h2">The sample gate</h2>
        <p>{data.sample_gate_text}</p>
      </section>

      <section className="mt-section">
        <h2 className="rc-h2">What can be called</h2>
        <p>
          Horizons are {data.horizons.join(", ")} days, and nothing else, so that records can be
          compared across callers. A thesis needs at least {data.min_thesis_chars} characters.
        </p>
        <p>
          The scoreable universe currently holds{" "}
          <b className="num">{data.universe.symbols.toLocaleString()}</b> symbols with a price
          series, freshest close <span className="num">{data.universe.newest_close}</span>, and the
          benchmark is current to{" "}
          <span className="num">{data.universe.benchmark_newest_close}</span>. A call on a symbol
          outside that universe is published and sealed as unscoreable, with the reason, rather than
          refused.
        </p>
      </section>

      <section className="mt-section mt-chain">
        <h2 className="rc-h2">What the chain does and does not prove</h2>
        <div className="mt-proves">
          <div className="mt-does">
            <div className="mt-does-h"><Icon name="shield" size={15} /> It proves</div>
            <p>{data.chain.proves}</p>
            <p className="mt-algo num">{data.chain.algorithm}</p>
            <p className="mt-fields">
              Sealed fields, in the order they are serialised:{" "}
              <span className="num">{data.chain.sealed_fields.join(", ")}</span>
            </p>
          </div>
          <div className="mt-doesnot">
            <div className="mt-does-h"><Icon name="alert" size={15} /> The limit</div>
            <p>{data.chain.does_not_prove}</p>
          </div>
        </div>
      </section>

      <Disclaimer text={data.disclaimer} />
    </div>
  );
}
