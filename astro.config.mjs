// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://videos.rapidmov.online',
  // nginx serves /foo and /foo/ the same page
  trailingSlash: 'ignore',
});
