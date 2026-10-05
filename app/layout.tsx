import type { Metadata } from "metadata"; // O puedes omitirlo si prefieres solo el HTML limpio

export const metadata: Metadata = {
  title: "BioRifa Solidaria 🧬",
  description: "Centro de Alumnos · Ingeniería Civil en Biotecnología · UFRO",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es">
      <head>
        {/* Esto inyecta Tailwind CSS para que el diseño moderno cargue de inmediato */}
        <script src="https://cdn.tailwindcss.com"></script>
      </head>
      <body className="bg-[#0b0715] text-emerald-50 min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}