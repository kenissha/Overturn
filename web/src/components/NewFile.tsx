import { useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";

// Opening a file: create a case, upload the denial letter, read it, go to it.
export function NewFile({ label = "New file" }: { label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function start(file: File) {
    setError(null);
    try {
      setStep("Opening a file");
      const created = await api.createCase();
      setStep("Storing and scanning the letter");
      await api.upload(created.case_id, file);
      setStep("Reading the letter");
      await api.process(created.case_id);
      navigate(`/case/${created.case_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStep(null);
    }
  }

  return (
    <span className="newfile">
      <button className="primary" disabled={step !== null} onClick={() => input.current?.click()}>
        {step ?? label}
      </button>
      <input
        ref={input}
        type="file"
        accept=".txt,.pdf,text/plain,application/pdf"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void start(file);
        }}
      />
      {error && <span className="error-inline">{error}</span>}
    </span>
  );
}
