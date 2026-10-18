"use client";

import { useCallback, useEffect, useState } from "react";

type InboxEmail = {
  id: string;
  subject: string;
  held_out: boolean;
  has_draft: boolean;
  category: string | null;
  risk_level: string | null;
  kb_status: string | null;
};

type Claim = { text: string; action: string; replacement?: string };

type Draft = {
  category: string;
  risk_level: string;
  kb_status: string;
  failure_reason: string | null;
  evidence: string;
  evidence_text: string;
  sources: string[];
  suggested_reply: string;
  draft_before_claim_check: string;
  unsupported_claims: Claim[];
  claim_check_passed: boolean;
  quality_check_passed: boolean;
  needs_human_approval: boolean;
  prompt_version: string;
  model_name: string;
  next_action: string;
};

type Autonomy = {
  category: string;
  consecutive_identical: number;
  eligible: boolean;
  trial_enabled: boolean;
  never_eligible: boolean;
};

type Detail = {
  email: { id: string; subject: string; body: string; held_out: boolean };
  draft: Draft | null;
};

export default function HomePage() {
  const [emails, setEmails] = useState<InboxEmail[]>([]);
  const [autonomy, setAutonomy] = useState<Autonomy[]>([]);
  const [health, setHealth] = useState<{ available: boolean; message: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [reply, setReply] = useState("");
  const [composer, setComposer] = useState<"none" | "edit" | "reject">("none");
  const [sendKey, setSendKey] = useState("");

  const loadInbox = useCallback(async () => {
    const response = await fetch("/api/inbox");
    const body = (await response.json()) as { emails: InboxEmail[]; autonomy: Autonomy[] };
    setEmails(body.emails);
    setAutonomy(body.autonomy);
  }, []);

  useEffect(() => {
    void loadInbox();
    void fetch("/api/kb-health")
      .then((response) => response.json())
      .then((body: { available: boolean; message: string }) => setHealth(body));
  }, [loadInbox]);

  async function openEmail(id: string) {
    setSelected(id);
    setMessage("");
    setError("");
    setComposer("none");
    setReason("");
    setReply("");
    setSendKey(crypto.randomUUID());
    const response = await fetch(`/api/inbox/${id}`);
    setDetail((await response.json()) as Detail);
  }

  async function draft() {
    if (!selected) return;
    setBusy(true);
    setError("");
    setMessage("Drafting from the knowledge service…");
    const response = await fetch(`/api/inbox/${selected}`, { method: "POST" });
    const body = (await response.json()) as Detail & { error?: string };
    setBusy(false);
    if (!response.ok) {
      setError(body.error || "Draft failed.");
      setMessage("");
      return;
    }
    setDetail(body);
    setMessage("Draft ready.");
    setSendKey(crypto.randomUUID());
    await loadInbox();
  }

  async function review(outcome: "approved" | "edited" | "rejected" | "needs_expert") {
    if (!selected) return;
    setBusy(true);
    setError("");
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        emailId: selected,
        outcome,
        reason,
        reply: outcome === "approved" || outcome === "needs_expert" ? undefined : reply,
        idempotencyKey: sendKey,
      }),
    });
    const body = (await response.json()) as { error?: string; message?: string; autonomy?: Autonomy[]; duplicate?: boolean };
    setBusy(false);
    if (!response.ok) {
      setError(body.error || "Review failed.");
      return;
    }
    setMessage(body.message || "Saved.");
    if (body.autonomy) setAutonomy(body.autonomy);
    if (!body.duplicate) setSendKey(crypto.randomUUID());
    await loadInbox();
  }

  async function toggleTrial(category: string, enabled: boolean) {
    setError("");
    const response = await fetch("/api/autonomy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category, enabled }),
    });
    const body = (await response.json()) as { error?: string; autonomy?: Autonomy[] };
    if (!response.ok) {
      setError(body.error || "Could not change the trial.");
      return;
    }
    if (body.autonomy) setAutonomy(body.autonomy);
  }

  const draftView = detail?.draft;
  const unavailable = draftView != null && draftView.kb_status !== "ok";

  return (
    <main className="shell">
      {health && !health.available ? <p className="banner">{health.message}</p> : null}
      {unavailable ? (
        <p className="banner">Knowledge service unavailable. {draftView?.failure_reason}</p>
      ) : null}
      <h1>Review inbox</h1>
      <p>Sends stay in a simulated outbox. Nothing leaves this machine.</p>
      {error ? <p className="error">{error}</p> : null}
      {message ? <p>{message}</p> : null}

      <h2>Consecutive identical approvals</h2>
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th>Count</th>
            <th>Status</th>
            <th>Trial</th>
          </tr>
        </thead>
        <tbody>
          {autonomy.map((row) => (
            <tr key={row.category}>
              <td>{row.category}</td>
              <td>{row.consecutive_identical}</td>
              <td>
                {row.never_eligible
                  ? "Never eligible"
                  : row.eligible
                    ? "Eligible for a controlled autonomy trial"
                    : `${20 - row.consecutive_identical} to go`}
              </td>
              <td>
                {row.never_eligible ? (
                  "Off"
                ) : (
                  <button
                    className="action secondary"
                    type="button"
                    disabled={!row.eligible && !row.trial_enabled}
                    onClick={() => void toggleTrial(row.category, !row.trial_enabled)}
                  >
                    {row.trial_enabled ? "Turn trial off" : "Turn trial on"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="layout">
        <ul className="list">
          {emails.map((email) => (
            <li key={email.id}>
              <button type="button" aria-current={selected === email.id ? "true" : undefined} onClick={() => void openEmail(email.id)}>
                <strong>{email.id}</strong> {email.subject}
              </button>
            </li>
          ))}
        </ul>
        <section className="detail">
          {!detail ? <p>Select an email.</p> : null}
          {detail ? (
            <>
              <h2>{detail.email.subject}</h2>
              <pre className="block">{detail.email.body}</pre>
              {!draftView ? (
                <button className="action" type="button" disabled={busy} onClick={() => void draft()}>
                  Draft reply
                </button>
              ) : (
                <>
                  <p className="meta">
                    <span>Category: {draftView.category}</span>
                    <span>Risk: {draftView.risk_level}</span>
                    <span>Evidence: {draftView.evidence}</span>
                    <span>Prompt: {draftView.prompt_version}</span>
                    <span>Model: {draftView.model_name}</span>
                  </p>
                  <h3>Retrieved evidence</h3>
                  <pre className="block">{draftView.evidence_text || "(none)"}</pre>
                  <ul>
                    {draftView.sources.map((url) => (
                      <li key={url}>
                        <a href={url}>{url}</a>
                      </li>
                    ))}
                  </ul>
                  <h3>Before claim check</h3>
                  <pre className="block">{draftView.draft_before_claim_check || "(empty)"}</pre>
                  <h3>Draft reply</h3>
                  <pre className="block">{draftView.suggested_reply || "(no reply drafted)"}</pre>
                  {draftView.unsupported_claims.length > 0 ? (
                    <>
                      <h3>Unsupported claims</h3>
                      <ul>
                        {draftView.unsupported_claims.map((claim) => (
                          <li key={claim.text}>
                            {claim.action}: {claim.text}
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                  <p>Next action: {draftView.next_action}</p>
                  <div className="actions">
                    <button className="action" type="button" disabled={busy || unavailable} onClick={() => void review("approved")}>
                      Approve and send
                    </button>
                    <button className="action secondary" type="button" disabled={busy} onClick={() => setComposer("edit")}>
                      Edit then send
                    </button>
                    <button className="action secondary" type="button" disabled={busy} onClick={() => setComposer("reject")}>
                      Reject and write replacement
                    </button>
                    <button className="action secondary" type="button" disabled={busy} onClick={() => void review("needs_expert")}>
                      Mark as needs expert
                    </button>
                    <button className="action secondary" type="button" disabled={busy} onClick={() => void draft()}>
                      Draft again
                    </button>
                  </div>
                  {composer !== "none" ? (
                    <>
                      <label>
                        {composer === "edit" ? "Edited reply" : "Replacement reply"}
                        <textarea rows={8} value={reply} onChange={(event) => setReply(event.target.value)} />
                      </label>
                      <label>
                        Reason (required)
                        <input value={reason} onChange={(event) => setReason(event.target.value)} type="text" />
                      </label>
                      <button
                        className="action"
                        type="button"
                        disabled={busy}
                        onClick={() => void review(composer === "edit" ? "edited" : "rejected")}
                      >
                        {composer === "edit" ? "Send edited reply" : "Send replacement"}
                      </button>
                    </>
                  ) : null}
                </>
              )}
            </>
          ) : null}
        </section>
      </div>
    </main>
  );
}
