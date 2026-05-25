export type Lang = 'en' | 'ko';

export const SITE_URL = 'https://youngkuklaw.com';

export const LANG_LABEL: Record<Lang, string> = {
  en: 'English',
  ko: '한국어',
};

export function isLang(value: string | undefined): value is Lang {
  return value === 'en' || value === 'ko';
}

/** Build a path for a given locale + slug (slug shared across EN/KO). */
export function localePath(lang: Lang, slug: string = ''): string {
  const normalised = slug.replace(/^\/+|\/+$/g, '');
  if (lang === 'en') return normalised === '' ? '/' : `/${normalised}/`;
  return normalised === '' ? '/ko/' : `/ko/${normalised}/`;
}

/**
 * Given the current pathname (e.g. "/ko/contract-law/"), return the equivalent
 * path in the opposite locale. Returns null when the opposite-locale page
 * does not exist (LangSwitcher should render disabled).
 */
export function oppositeLocalePath(currentPath: string, currentLang: Lang): string {
  const trimmed = currentPath.replace(/\/+$/, '') || '/';
  if (currentLang === 'en') {
    if (trimmed === '/') return '/ko/';
    return `/ko${trimmed.endsWith('/') ? trimmed : trimmed + '/'}`;
  }
  // currentLang === 'ko'
  if (trimmed === '/ko') return '/';
  const stripped = trimmed.replace(/^\/ko/, '') || '/';
  return stripped.endsWith('/') ? stripped : stripped + '/';
}

export const CATEGORY_LABELS: Record<string, { en: string; ko: string }> = {
  'english-law':         { en: 'English Law',         ko: '영국법 일반' },
  'contract-law':        { en: 'Contract',            ko: '계약법' },
  'tort-law':            { en: 'Tort',                ko: '불법행위법' },
  'public-law':          { en: 'Public',              ko: '공법' },
  'criminal-law':        { en: 'Criminal',            ko: '형사법' },
  'equity-law':          { en: 'Equity',              ko: '형평법' },
  'land-law':            { en: 'Land',                ko: '토지법' },
  'case-law':            { en: 'All Cases',           ko: '모든 판례' },
  'contract-law-cases':  { en: 'Contract Cases',      ko: '계약법 판례' },
  'tort-law-cases':      { en: 'Tort Cases',          ko: '불법행위법 판례' },
  'public-law-cases':    { en: 'Public Cases',        ko: '공법 판례' },
  'criminal-law-cases':  { en: 'Criminal Cases',      ko: '형사법 판례' },
  'equity-law-cases':    { en: 'Equity Cases',        ko: '형평법 판례' },
  'land-law-cases':      { en: 'Land Cases',          ko: '토지법 판례' },
};
