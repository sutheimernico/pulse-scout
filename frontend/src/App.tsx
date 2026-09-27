import { useEffect, useState } from "react";

import { type LoadResult, loadLatest } from "./api";
import {
  TIER_LABELS,
  berlinToday,
  formatDigestDate,
  formatStand,
  funnelShare,
  groupKuer,
  offlineNotice,
  rank,
  readTimeLabel,
  staleNotice,
} from "./format";
import type { Card, Digest } from "./types";

export function App({ token }: { token: string | null }) {
  const [result, setResult] = useState<LoadResult | null>(null);

  useEffect(() => {
    let active = true;
    loadLatest(token).then((next) => {
      if (active) setResult(next);
    });
    return () => {
      active = false;
    };
  }, [token]);

  if (result === null) return <Shell message="Lade den Digest …" />;
  switch (result.kind) {
    case "unauthorized":
      return (
        <Shell message="Kein Zugang. Öffne die Seite einmal mit deinem Token: …/?token=DEIN_TOKEN — danach merkt sich das Handy den Zugang." />
      );
    case "none":
      return <Shell message="Noch kein Digest gebaut. Der erste entsteht beim nächsten abendlichen Lauf." />;
    case "unreachable":
      return (
        <Shell message="Der Server ist nicht erreichbar, und auf diesem Gerät ist noch kein Digest gespeichert." />
      );
    case "ok":
      return <DigestView digest={result.digest} offlineSince={result.offlineSince} />;
  }
}

function Shell({ message }: { message: string }) {
  return (
    <div className="phone">
      <header>
        <div className="head-row">
          <p className="wordmark">pulse · scout</p>
        </div>
      </header>
      <p className="status">{message}</p>
    </div>
  );
}

function DigestView({ digest, offlineSince }: { digest: Digest; offlineSince: string | null }) {
  const seen = digest.counters.items_seen ?? 0;
  const kept = digest.cards.length;
  const stale = staleNotice(digest.digest_date, berlinToday(new Date()));
  const groups = groupKuer(digest.kuer);

  return (
    <div className="phone">
      <header>
        <div className="head-row">
          <p className="wordmark">pulse · scout</p>
          <p className="readtime">{readTimeLabel(digest.read_seconds)}</p>
        </div>
        <h1 className="datum">{formatDigestDate(digest.digest_date)}</h1>
        <p className="stand">Stand {formatStand(digest.generated_at)}</p>
        <div className="funnel" aria-label={`${seen} gesichtet, ${kept} für dich`}>
          <span>{seen} gesichtet</span>
          <span className="funnel-bar">
            <i style={{ width: `${funnelShare(seen, kept)}%` }} />
          </span>
          <span>{kept} für dich</span>
        </div>
      </header>

      {offlineSince !== null && <p className="banner">{offlineNotice(offlineSince)}</p>}
      {stale && <p className="banner">{stale}</p>}
      {digest.notes.length > 0 && (
        <ul className="notes">
          {digest.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <Marker label="Heute" count={String(kept)} />
      <div className="cards">
        {kept === 0 && <p className="status">Heute hat nichts einen Platz verdient.</p>}
        {digest.cards.map((card, index) => (
          <CardView key={card.item_key} card={card} index={index} />
        ))}
      </div>

      {digest.thread && (
        <>
          <Marker label="Roter Faden" />
          <div className="lede">
            <p>{digest.thread}</p>
          </div>
        </>
      )}

      {groups.length > 0 && (
        <>
          <Marker label="Kür" count={`${digest.kuer.length} Zeilen`} />
          <div className="kuer">
            {groups.map((group) => (
              <details key={group.tier}>
                <summary>
                  <b>{group.label}</b>
                  <em>{group.lines.length}</em>
                </summary>
                <ul>
                  {group.lines.map((line) => (
                    <li key={`${line.source_name}-${line.title}`}>
                      {line.url ? (
                        <a href={line.url} target="_blank" rel="noopener noreferrer">
                          {line.title}
                        </a>
                      ) : (
                        line.title
                      )}
                      <span>{line.source_name}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </>
      )}

      <Footer digest={digest} />
    </div>
  );
}

function Marker({ label, count }: { label: string; count?: string }) {
  return (
    <div className="marker">
      <b>{label}</b>
      <i />
      {count && <em>{count}</em>}
    </div>
  );
}

function CardView({ card, index }: { card: Card; index: number }) {
  return (
    <article>
      <div className="meta">
        <span className="rank">{rank(index)}</span>
        <span className="dot">•</span>
        <span>{TIER_LABELS[card.tier] ?? `Stufe ${card.tier}`}</span>
        <span className="dot">•</span>
        <span>{card.source_name}</span>
      </div>
      <h3>{card.headline}</h3>
      {card.quoted ? (
        <p className="quoted">
          <b>Originaltext der Quelle</b>
          <span lang="en">{card.body}</span>
        </p>
      ) : (
        <p>{card.body}</p>
      )}
      <div className="why">
        <b>Darum geht’s dich an</b>
        {card.why_you}
      </div>
      {card.url && (
        <a className="source" href={card.url} target="_blank" rel="noopener noreferrer">
          Zur Quelle: {card.source_name} →
        </a>
      )}
    </article>
  );
}

function Footer({ digest }: { digest: Digest }) {
  const guard = digest.guard && "checked" in digest.guard ? digest.guard : null;
  const c = digest.counters;
  return (
    <footer>
      <p>
        Lauf: {c.items_seen ?? 0} gesichtet, {c.items_new ?? 0} neu, {c.candidates ?? 0} Kandidaten
        {c.sources_failed ? `, ${c.sources_failed} Quellen ausgefallen` : ""}.
      </p>
      {guard ? (
        <p>
          Faktencheck ({guard.model}): {guard.checked} Sätze gegen ihre Quelle geprüft,{" "}
          {guard.rejected} verworfen. „Darum geht’s dich an“ und der Rote Faden sind Einordnung
          und werden nicht geprüft.
        </p>
      ) : (
        <p>Dieser Digest wurde vor dem Faktencheck gebaut — seine Sätze sind ungeprüft.</p>
      )}
    </footer>
  );
}
