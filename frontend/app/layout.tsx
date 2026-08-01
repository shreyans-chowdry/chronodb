import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ChronoDB — Version-Controlled Database Dashboard",
  description:
    "Git-like version control for relational data. Branch, commit, rollback, and time-travel query your database.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} dark h-full antialiased`}>
      <body className="min-h-full bg-zinc-950 font-sans text-zinc-100">
        {children}
      </body>
    </html>
  );
}
