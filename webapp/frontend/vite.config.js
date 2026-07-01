import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',          // listen on all interfaces (tunnel needs this)
    port: 5173,
    strictPort: true,         // fail if 5173 is taken instead of silently switching
    allowedHosts: [
      'localhost',
      '127.0.0.1',
      '.devtunnels.ms',       // wildcard for all Dev Tunnel subdomains
    ],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    hmr: {
      clientPort: 443,        // tunnel terminates HTTPS on 443
                              // without this, HMR websocket fails
    },
  },
})