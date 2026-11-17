import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// W trybie deweloperskim /api trafia do lokalnego backendu (to samo pochodzenie => cookie sesji działa).
// W produkcji to samo robi nginx (patrz nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
