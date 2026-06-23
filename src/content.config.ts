import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'zod';

const CATEGORY_SLUGS = [
  'english-law',
  'contract-law',
  'tort-law',
  'public-law',
  'criminal-law',
  'equity-law',
  'land-law',
  'case-law',
  'contract-law-cases',
  'tort-law-cases',
  'public-law-cases',
  'criminal-law-cases',
  'equity-law-cases',
  'land-law-cases',
] as const;

const posts = defineCollection({
  loader: glob({
    pattern: '**/*.{md,mdx}',
    base: './src/content/posts',
    generateId: ({ entry }) => entry.replace(/\.[^/.]+$/, ''),
  }),
  schema: z.object({
    lang: z.enum(['en', 'ko']),
    title: z.string(),
    description: z.string(),
    slug: z.string(),
    category: z.enum(CATEGORY_SLUGS),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    seoTitle: z.string().optional(),
    metaDescription: z.string().optional(),
    focusKeyphrase: z.string().optional(),
    longTailKeywords: z.array(z.string()).default([]),
    uiTags: z.array(z.string()).default([]),
    uiDescription: z.string().optional(),
    ogImage: z.string().optional(),
    wpId: z.number().int().optional(),
    sourceOrigin: z.enum(['migrated', 'newly-written']).default('newly-written'),
    humanReviewed: z.boolean().default(false),
    brokenLinks: z.array(z.string()).default([]),
    draft: z.boolean().default(false),
    isDummy: z.boolean().default(false),
    citation: z.string().optional(),
    court: z.string().optional(),
    claimantRole: z.string().optional(),
    claimant: z.string().optional(),
    defendantRole: z.string().optional(),
    defendant: z.string().optional(),
    courtLink: z.string().optional(),
  }),
});

export const collections = { posts };

export const categorySlugs = CATEGORY_SLUGS;
export type CategorySlug = (typeof CATEGORY_SLUGS)[number];
