import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IntakeFlow | Evidence-first intake operations",
  description: "A synthetic, auditable healthcare administrative intake workflow.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
