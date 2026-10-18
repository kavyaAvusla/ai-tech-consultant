import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Inbox agent",
  description: "Support inbox drafts grounded in the Knowledge Brain.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
