import "./globals.css";

export const metadata = {
  title: "WarControl",
  description: "NationGlory live dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
