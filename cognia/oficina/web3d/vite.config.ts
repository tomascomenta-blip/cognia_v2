import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Servido por el backend en GET /oficina3d/* (cognia/oficina/server.py).
export default defineConfig({
  base: '/oficina3d/',
  plugins: [react(), tailwindcss()],
  server: {
    // dev suelto (npm run dev): el backend real de la oficina corre en 8765
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
