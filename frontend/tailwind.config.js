/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0d1117",
        surface: "#161b22",
        surfaceBorder: "#30363d",
        primary: "#58a6ff",
        accent: "#238636",
        danger: "#da3633",
        warning: "#d29922",
      },
    },
  },
  plugins: [],
}
