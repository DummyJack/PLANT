/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "Noto Sans TC",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
      },
      fontSize: {
        body: ["0.875rem", { lineHeight: "1.5" }], // 14px
        meta: ["0.75rem", { lineHeight: "1.4" }], // 12px
      },
      borderRadius: {
        surface: "0.75rem", // rounded-xl — panels, cards
        control: "0.5rem", // rounded-lg — buttons, inputs
        bubble: "1rem", // rounded-2xl — chat bubbles
      },
    },
  },
  plugins: [],
};
