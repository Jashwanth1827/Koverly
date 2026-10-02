/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#d9e5ff",
          200: "#bcd0ff",
          300: "#8eb0ff",
          400: "#5985ff",
          500: "#335cff",
          600: "#1d3bf5",
          700: "#172be1",
          800: "#1925b6",
          900: "#1b268f",
        },
        ink: {
          900: "#0b1220",
          700: "#25304a",
          500: "#5a6785",
          300: "#9aa5be",
        },
        surface: "#f6f8fc",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
