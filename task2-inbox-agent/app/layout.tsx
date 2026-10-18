import type { ReactNode } from "react";
import Link from "next/link";
import "./globals.css";

export const metadata = {
  title: "Inbox agent",
  description: "Review support drafts grounded in the Knowledge Brain.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <strong>Inbox agent</strong>
          <nav>
            <Link href="/">Inbox</Link>
            <Link href="/outbox">Outbox (SIMULATED)</Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
