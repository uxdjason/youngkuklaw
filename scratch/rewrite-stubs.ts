import fs from 'fs';
import path from 'path';

const CATEGORIES = [
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
];

const PAGES_DIR = path.resolve(import.meta.dirname || process.cwd(), '../src/pages');

// Rewrite EN stubs
for (const cat of CATEGORIES) {
  const dir = path.join(PAGES_DIR, cat);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  
  const file = path.join(dir, 'index.astro');
  const content = `---
import CategoryLayout from '../../layouts/CategoryLayout.astro';
---
<CategoryLayout lang="en" category="${cat}" />
`;
  fs.writeFileSync(file, content, 'utf8');
}

// Rewrite KO stubs
for (const cat of CATEGORIES) {
  const dir = path.join(PAGES_DIR, 'ko', cat);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  
  const file = path.join(dir, 'index.astro');
  const content = `---
import CategoryLayout from '../../../layouts/CategoryLayout.astro';
---
<CategoryLayout lang="ko" category="${cat}" />
`;
  fs.writeFileSync(file, content, 'utf8');
}

console.log('Successfully rewrote 28 category stubs.');
