export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <head>
        <script src="https://cdn.tailwindcss.com"></script>
      </head>
      <body className="bg-[#0b0715] text-emerald-50 min-h-screen antialiased selection:bg-[#39ff88] selection:text-black">
        {children}
      </body>
    </html>
  );
}