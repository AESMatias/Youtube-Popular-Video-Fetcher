import { videoSlug } from './slug';

export interface Language {
  code: string;
  name: string;
  count: number;
}

export interface Video {
  video_id: string;
  lang: string;
  rank: number;
  title: string;
  channel_title: string;
  published_at: string;
  view_count: number;
  like_count: number | null;
  comment_count: number | null;
  duration: string | null;
  thumbnail_url: string;
  youtube_url: string;
  description: string | null;
  seo_title: string | null;
  seo_description: string | null;
  times_featured: number;
  first_seen: string;
  slug: string;
}

interface SiteData {
  updated_at: string;
  languages: Language[];
  videos: Omit<Video, 'slug'>[];
}

// Glob instead of import so a fresh clone without site.json still builds.
const site = Object.values(import.meta.glob<SiteData>('../data/site.json', { eager: true, import: 'default' }))[0];

export const updatedAt: string | null = site?.updated_at ?? null;
export const languages: Language[] = site?.languages ?? [];
export const videos: Video[] = (site?.videos ?? []).map((v) => ({ ...v, slug: videoSlug(v) }));

export const videosByLang = (code: string): Video[] =>
  videos.filter((v) => v.lang === code).sort((a, b) => a.rank - b.rank);

export const languageName = (code: string): string => languages.find((l) => l.code === code)?.name ?? code;

// The same video can trend in several languages but only gets one page, the first entry wins.
const seen = new Set<string>();
export const videoPages: Video[] = videos.filter((v) => !seen.has(v.video_id) && seen.add(v.video_id));

// summaries may have **markdown**, show them as plain text
export const stripMarkdown = (text: string): string =>
  text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1');

// spread into code points so emoji are not cut in half
export const excerpt = (text: string, max: number): string => {
  const chars = [...text.replace(/\s+/g, ' ').trim()];
  return chars.length > max ? chars.slice(0, max - 1).join('').trimEnd() + '…' : chars.join('');
};

const URL_RE = /https?:\/\/[^\s<>"'`]+/g;
// Trailing punctuation is almost always the sentence, not the link.
const TRAILING = /[.,;:!?)\]}'"»]+$/;

export type TextPart = { text: string } | { href: string; label: string };

// split into text and links so we can render <a> without set:html
export const linkify = (text: string): TextPart[] => {
  const parts: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const href = m[0].replace(TRAILING, '');
    const start = m.index!;
    if (start > last) parts.push({ text: text.slice(last, start) });
    const bare = [...href.replace(/^https?:\/\/(www\.)?/, '')];
    parts.push({ href, label: bare.length > 32 ? bare.slice(0, 31).join('') + '…' : bare.join('') });
    last = start + href.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
};

// Cards should read as text, so links, #hashtags and @handles go.
export const plainText = (text: string): string =>
  text
    .replace(URL_RE, '')
    .replace(/(^|\s)[#@]\p{L}[\p{L}\p{N}_.]*/gu, '$1')
    // "Stream here: <link>" would leave a dangling colon or arrow at the end of the line.
    .replace(/[ \t]*[:|•►▶→–-]+[ \t]*$/gm, '')
    .replace(/\s+/g, ' ')
    .trim();

const compact =new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
export const formatCount = (n: number | null | undefined): string | null => (n == null ? null : compact.format(n));

// PT4M13S -> 4:13, PT1H2M3S -> 1:02:03. Live streams come as P0D, which we hide.
export const formatDuration = (iso: string | null | undefined): string | null => {
  const m = iso?.match(/^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/);
  if (!m) return null;
  const [d, h, min, s] = m.slice(1).map((x) => Number(x ?? 0));
  const hours = d * 24 + h;
  if (!hours && !min && !s) return null;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours ? `${hours}:${pad(min)}:${pad(s)}` : `${min}:${pad(s)}`;
};

// UTC so the date does not depend on the build machine's timezone.
export const formatDate = (iso: string | null | undefined): string | null => {
  const date = new Date(iso ?? '');
  return isNaN(date.getTime()) ? null : date.toLocaleDateString('en-US', { dateStyle: 'medium', timeZone: 'UTC' });
};

// Goes into a <script> tag, so a "</script>" inside a title must not close it.
export const jsonLd = (data: object): string => JSON.stringify(data).replace(/</g, '\\u003c');
