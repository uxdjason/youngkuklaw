import fs from 'fs';
import path from 'path';

const EN_DIR = path.resolve(import.meta.dirname || process.cwd(), '../src/content/posts/en/_dummies');
const KO_DIR = path.resolve(import.meta.dirname || process.cwd(), '../src/content/posts/ko/_dummies');

function purgeDir(dirPath: string) {
  if (fs.existsSync(dirPath)) {
    fs.rmSync(dirPath, { recursive: true, force: true });
    console.log(`Purged directory: ${dirPath}`);
  } else {
    console.log(`Directory does not exist, skipping: ${dirPath}`);
  }
}

purgeDir(EN_DIR);
purgeDir(KO_DIR);

console.log('Dummy content purged successfully.');
