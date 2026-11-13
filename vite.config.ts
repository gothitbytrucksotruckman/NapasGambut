/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' keeps asset paths relative so the site works under any GitHub Pages repo path.
export default defineConfig({
  base: './',
  plugins: [react()],
  test: { environment: 'node', include: ['tests/**/*.test.ts'], testTimeout: 60000 },
});
