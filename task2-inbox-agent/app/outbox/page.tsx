"use client";

import { useEffect, useState } from "react";

type Sent = {
  id: number;
  email_id: string;
  category: string;
  body: string;
  created_at: string;
  label: string;
};

export default function OutboxPage() {
  const [rows, setRows] = useState<Sent[]>([]);

  useEffect(() => {
    void fetch("/api/outbox")
      .then((response) => response.json())
      .then((body: { rows: Sent[] }) => setRows(body.rows));
  }, []);

  return (
    <main className="shell">
      <p className="sim-banner">SIMULATED — this outbox does not deliver email.</p>
      <h1>Sent table</h1>
      <table>
        <thead>
          <tr>
            <th>Label</th>
            <th>When</th>
            <th>Email</th>
            <th>Category</th>
            <th>Body</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.label}</td>
              <td>{row.created_at}</td>
              <td>{row.email_id}</td>
              <td>{row.category}</td>
              <td>{row.body}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 ? <p>No simulated sends yet.</p> : null}
    </main>
  );
}
