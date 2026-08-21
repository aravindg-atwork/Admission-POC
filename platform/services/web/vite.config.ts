import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxies /api/* to the local backend SERVER-SIDE, inside the dev
    // server process - not in the browser. This is what makes remote
    // testing through a tunnel (devtunnels, ngrok, etc.) actually work:
    // the browser only ever calls a RELATIVE path on whatever origin the
    // page itself was loaded from, so it works identically whether that
    // origin is http://localhost:5175 or a random tunnel hostname. Baking
    // an absolute http://localhost:8100 into the frontend bundle (the
    // previous approach) only ever worked on the same machine running the
    // backend - broke immediately the first time this was shared with
    // someone testing from their own machine.
    proxy: {
      '/api': 'http://localhost:8100',
    },
  },
})
