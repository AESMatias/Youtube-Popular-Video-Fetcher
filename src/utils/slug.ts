// Accents are stripped first ("Árbol" -> "arbol"), so ASCII titles give the same slug as before.
export const createSlug = (title: string | null | undefined): string => {
  return (title ?? '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9 -]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
};

// Don't change this format, live URLs depend on it. Titles with no latin letters or digits
// (Japanese, emoji only...) get the bare id instead of a dangling "id-".
export const videoSlug = (video: { video_id: string; title?: string | null }): string => {
  const slug = createSlug(video.title);
  return /[a-z0-9]/.test(slug) ? `${video.video_id}-${slug}` : video.video_id;
};
