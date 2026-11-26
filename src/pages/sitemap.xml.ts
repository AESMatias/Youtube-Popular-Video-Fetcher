import type { APIRoute } from 'astro';
import { languages, videoPages, updatedAt } from '../utils/data';

const escapeXml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export const GET: APIRoute = ({ site }) => {
  const base = site ?? 'https://videos.rapidmov.online';
  const paths = ['/', '/about', ...languages.map((l) => `/lang/${l.code}`), ...videoPages.map((v) => `/videos/${v.slug}`)];
  const lastmod = updatedAt ? `<lastmod>${escapeXml(updatedAt)}</lastmod>` : '';
  const urls = paths.map((p) => `  <url><loc>${escapeXml(new URL(p, base).href)}</loc>${lastmod}</url>`);

  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`,
    { headers: { 'Content-Type': 'application/xml; charset=utf-8' } },
  );
};
