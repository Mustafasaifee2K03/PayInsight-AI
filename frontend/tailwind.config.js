/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#07142b", 900: "#0b1f3f", 800: "#12305c", 700: "#1a427a", 600: "#245597" },
        brand: { 50: "#eef5fe", 100: "#cde2fb", 300: "#6da7ec", 500: "#2a78d6", 600: "#256abf", 700: "#1c5cab" },
      },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "Consolas", "monospace"] },
    },
  },
  plugins: [],
};
