/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Ubuntu', 'system-ui', 'sans-serif'],
      },
      colors: {
        slate: {
          100: '#e2e8f0',
          200: '#c8d0da',
          300: '#aab2c0',
          400: '#8892a4',
          500: '#3d4460',
          600: '#2e3348',
          700: '#22263a',
          800: '#1a1d26',
          900: '#0f1117',
          950: '#080a0f',
        },
        lemon: {
          300: '#ffe580',
          400: '#ffd340',
          500: '#ffc832',
          600: '#e6a800',
          700: '#b37f00',
        },
      },
    },
  },
  plugins: [],
}
