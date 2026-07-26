// The page. Five bands in the order the brief sets, plus the structured data a search engine reads.
import { useEffect } from "react";
import { Close, Faq, FAQS, Hero, Ledger, Personalisation, Walkthrough } from "./sections.jsx";

const APP = "/";

// FAQPage structured data, generated from the SAME array the accordion renders. Written as one
// object rather than duplicated into the HTML head, because a hand-maintained copy is a copy that
// eventually disagrees with the page — and structured data that disagrees with the visible answer
// is the kind of thing search engines penalise and readers notice.
function StructuredData() {
  useEffect(() => {
    const el = document.createElement("script");
    el.type = "application/ld+json";
    el.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "FAQPage",
          mainEntity: FAQS.map((f) => ({
            "@type": "Question",
            name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a },
          })),
        },
        {
          "@type": "SoftwareApplication",
          name: "Rhumb",
          applicationCategory: "FinanceApplication",
          operatingSystem: "Web",
          description:
            "Rhumb interprets world events into their market consequences — mechanism, assets, " +
            "horizon and confidence — and publishes its own accuracy record, misses first.",
          offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
        },
      ],
    });
    document.head.appendChild(el);
    return () => el.remove();
  }, []);
  return null;
}

export function App() {
  return (
    <>
      <StructuredData />
      <a className="skip" href="#how">Skip to content</a>

      <nav className="nav">
        <span className="nav-mark">Rhumb</span>
        <div className="nav-links">
          <a href="#how">How it works</a>
          <a href="#ledger">Accuracy</a>
          <a href="#you">Personalisation</a>
          <a href="#faq">FAQ</a>
        </div>
        <a className="btn" href="/auth" style={{ padding: "9px 18px", fontSize: 14 }}>Start free</a>
      </nav>

      <main>
        <Hero />
        <Walkthrough />
        <Ledger />
        <Personalisation />
        <Faq />
        <Close />
      </main>

      <footer className="foot">
        <div className="wrap">
          <div className="foot-grid">
            <span className="nav-mark">Rhumb</span>
            <a href={APP} style={{ color: "var(--paper-dim)" }}>Open the app</a>
            <a href="#ledger" style={{ color: "var(--paper-dim)" }}>Accuracy record</a>
          </div>
          <p className="disc">
            Rhumb publishes informational analysis of public information. It is not personalised
            investment advice, it does not know your circumstances, and it is wrong more often than
            it is right — the Ledger above is the actual number, not a disclaimer. Market data and
            filings are sourced from SEC EDGAR, public RSS, Nasdaq, CoinGecko and Tiingo; every
            figure in the product carries its source and its timestamp.
          </p>
        </div>
      </footer>
    </>
  );
}
