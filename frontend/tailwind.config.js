/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Pastel Unicorn Theme
        unicorn: {
          pink: {
            50: '#fef7f9',
            100: '#fdeef3',
            200: '#fbd5e5',
            300: '#f9b3d1',
            400: '#f687b3',
            500: '#ed64a6',
            600: '#d53f8c',
          },
          purple: {
            50: '#faf5ff',
            100: '#f3e8ff',
            200: '#e9d5ff',
            300: '#d8b4fe',
            400: '#c084fc',
            500: '#a855f7',
            600: '#9333ea',
          },
          blue: {
            50: '#f0f9ff',
            100: '#e0f2fe',
            200: '#bae6fd',
            300: '#7dd3fc',
            400: '#38bdf8',
            500: '#0ea5e9',
          },
          mint: {
            50: '#f0fdfa',
            100: '#ccfbf1',
            200: '#99f6e4',
            300: '#5eead4',
            400: '#2dd4bf',
            500: '#14b8a6',
          },
          lavender: {
            50: '#faf5ff',
            100: '#f3e8ff',
            200: '#ede4ff',
            300: '#ddd6fe',
            400: '#c4b5fd',
            500: '#a78bfa',
          },
        },
      },
      backgroundImage: {
        'unicorn-gradient': 'linear-gradient(135deg, #fdeef3 0%, #e9d5ff 25%, #bae6fd 50%, #ccfbf1 75%, #fdeef3 100%)',
        'unicorn-sidebar': 'linear-gradient(180deg, #2d1f3d 0%, #1a1625 100%)',
      },
    },
  },
  plugins: [],
};
