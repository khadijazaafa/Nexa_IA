/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#F5F2FF",
          100: "#EAE3FF",
          500: "#8064E8",
          600: "#6D4BD1",
          700: "#5737B5",
        },
      },
      boxShadow: {
        soft: "0 8px 30px rgba(48, 36, 91, 0.06)",
      },
    },
  },
  plugins: [],
};