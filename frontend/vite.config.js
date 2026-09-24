import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on :5173. It talks to the FastAPI backend on :8000 cross-origin, which is why the
// backend enables CORS for this origin (see chatbot/api/main.py). Override the backend URL with
// VITE_API_BASE if it runs elsewhere.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
