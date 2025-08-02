// This file contains utility functions for creating slugs from titles.
// It is used to generate URL-friendly strings from video titles.

export const createSlug = (title: string): string => {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9 -]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
};