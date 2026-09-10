import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import { fmtDate } from "./format";
import { CaseList } from "./screens/CaseList";
import { CaseView } from "./screens/CaseView";
import { Queue } from "./screens/Queue";

function useHashRoute(): string[] {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash.replace(/^#\/?/, "").split("/").filter(Boolean);
}

export function navigate(path: string) {
  window.location.hash = path;
}

export function App() {
  const route = useHashRoute();
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  const today = new Date().toISOString().slice(0, 10);
  const [section, id, tab] = route;

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="#/">
          Overturn
        </a>
        <nav>
          <a href="#/" className={!section ? "on" : ""}>
            Today
          </a>
          <a href="#/files" className={section === "files" ? "on" : ""}>
            All files
          </a>
        </nav>
        <div className="topbar-right">
          {health && !health.extractor && (
            <span className="notice" title="Set OVERTURN_EXTRACTOR=model on the API to enable reading">
              Reading is off — documents are stored and scanned, not read
            </span>
          )}
          <span className="muted">{fmtDate(today)}</span>
        </div>
      </header>
      <main>
        {section === "case" && id ? (
          <CaseView caseId={id} tab={tab ?? "ledger"} extractor={health?.extractor ?? false} />
        ) : section === "files" ? (
          <CaseList />
        ) : (
          <Queue extractor={health?.extractor ?? false} />
        )}
      </main>
    </div>
  );
}
