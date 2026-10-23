import type { Metadata } from "next";
import "./globals.css";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Overview · NexusCore",
  description: "Tenant observation overview",
  robots: { index: false, follow: false },
};

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
