/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#081233", 900: "#0F1F4B", 800: "#16295F", 700: "#1E3A8A", 600: "#24449E" },
        royal: { 50: "#EEF4FF", 100: "#DBE6FE", 200: "#BFD3FE", 500: "#2563EB", 600: "#1D4ED8", 700: "#1E40AF" },
        brandred: { 50: "#FEF2F2", 500: "#EF4444", 600: "#DC2626", 700: "#B91C1C" },
      },
      fontFamily: { sans: ["Inter", "Segoe UI", "Roboto", "system-ui", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(15,31,75,.06), 0 4px 16px rgba(15,31,75,.06)", lift: "0 8px 30px rgba(15,31,75,.14)" },
    },
  },
  plugins: [],
};
