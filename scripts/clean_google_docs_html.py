#!/usr/bin/env python3
import os
import sys
import glob
import re
from bs4 import BeautifulSoup

def clean_html(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Extract styles and find bold/italic/underline classes
    style_tags = soup.find_all('style')
    css_text = "\n".join([tag.string for tag in style_tags if tag.string])
    
    bold_classes = set()
    italic_classes = set()
    underline_classes = set()
    
    blocks = css_text.split('}')
    for block in blocks:
        if '{' not in block:
            continue
        selectors_str, rules_str = block.split('{', 1)
        selectors = [s.strip() for s in selectors_str.split(',')]
        
        is_bold = 'font-weight: 700' in rules_str or 'font-weight: bold' in rules_str or 'font-weight:700' in rules_str or 'font-weight:bold' in rules_str
        is_italic = 'font-style: italic' in rules_str or 'font-style:italic' in rules_str
        is_underline = 'text-decoration: underline' in rules_str or 'text-decoration:underline' in rules_str
        
        for sel in selectors:
            if sel.startswith('.'):
                cls_name = sel.split(':')[0].split(' ')[0][1:]
                if is_bold:
                    bold_classes.add(cls_name)
                if is_italic:
                    italic_classes.add(cls_name)
                if is_underline:
                    underline_classes.add(cls_name)
                    
    # 2. Traverse and replace elements with semantic tags
    for tag in soup.find_all(True):
        # We skip elements that are nav-buttons to not break idempotency if run multiple times
        if tag.has_attr('class') and 'nav-buttons' in tag['class']:
            continue
            
        if not tag.has_attr('class'):
            continue
            
        classes = tag['class']
        needs_bold = any(c in bold_classes for c in classes)
        needs_italic = any(c in italic_classes for c in classes)
        needs_underline = any(c in underline_classes for c in classes)
        
        del tag['class']
        if tag.has_attr('style'):
            del tag['style']
            
        if needs_bold or needs_italic or needs_underline:
            inner_html = "".join(str(c) for c in tag.contents)
            
            if needs_bold:
                inner_html = f"<strong>{inner_html}</strong>"
            if needs_italic:
                inner_html = f"<em>{inner_html}</em>"
            if needs_underline:
                inner_html = f"<u>{inner_html}</u>"
            
            tag.clear()
            tag.append(BeautifulSoup(inner_html, 'html.parser'))
            
            if tag.name == 'span':
                tag.unwrap()

    # 3. Strip all old style and script tags
    for tag in soup.find_all(['style', 'script']):
        tag.decompose()
        
    # 4. Clean empty spans
    for span in soup.find_all('span'):
        if not span.attrs:
            span.unwrap()

    # 5. Remove class/style from any remaining tags globally
    for tag in soup.find_all(True):
        if tag.has_attr('class') and 'nav-btn' in tag['class']:
            continue
        if tag.has_attr('class') and 'nav-buttons' in tag['class']:
            continue
            
        if tag.has_attr('class'):
            del tag['class']
        if tag.has_attr('style'):
            del tag['style']

    # 6. SEO Extractions
    head = soup.find('head')
    if not head:
        head = soup.new_tag('head')
        soup.insert(0, head)
        
    html_tag = soup.find('html')
    if html_tag:
        html_tag['lang'] = 'en'
        
    # Base configuration
    site_url = 'https://youngkuklaw.com'
    canonical_url = f"{site_url}/case-archive/{os.path.basename(filepath)}"
        
    # Extract Title from filename
    filename_title = os.path.splitext(os.path.basename(filepath))[0].replace('-', ' ').title()
    page_title = f"{filename_title} · YoungkukLaw"
    
    # Try to find an existing title and replace it, otherwise create one
    title_tag = soup.find('title')
    if not title_tag:
        title_tag = soup.new_tag('title')
        head.append(title_tag)
    title_tag.string = page_title
    
    # Extract Description (first ~150 chars of text)
    body = soup.find('body')
    description = ""
    if body:
        # Strip text and remove excessive whitespace
        raw_text = re.sub(r'\s+', ' ', body.get_text(separator=' ', strip=True))
        # Exclude URL links that might be at the top
        raw_text = re.sub(r'https?://[^\s]+', '', raw_text).strip()
        description = raw_text[:155] + ('...' if len(raw_text) > 155 else '')
        
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        if not desc_tag:
            desc_tag = soup.new_tag('meta', attrs={'name': 'description', 'content': description})
            head.append(desc_tag)
        else:
            desc_tag['content'] = description

    # Canonical URL
    canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
    if not canonical_tag:
        canonical_tag = soup.new_tag('link', rel='canonical', href=canonical_url)
        head.append(canonical_tag)
    else:
        canonical_tag['href'] = canonical_url

    # Open Graph Tags
    og_tags = {
        'og:title': page_title,
        'og:description': description,
        'og:type': 'article',
        'og:url': canonical_url,
        'og:image': f"{site_url}/images/og-default.png",
        'og:site_name': 'YoungkukLaw'
    }
    
    for prop, content in og_tags.items():
        meta_tag = soup.find('meta', attrs={'property': prop})
        if not meta_tag:
            meta_tag = soup.new_tag('meta', property=prop, content=content)
            head.append(meta_tag)
        else:
            meta_tag['content'] = content
            
    # AdSense Preparation
    # The user can replace YOUR_ADSENSE_ID_HERE when ready
    # Remove any existing AdSense placeholders first to avoid duplicates or keeping commented ones
    for script_tag in soup.find_all('script'):
        if script_tag.has_attr('src') and 'adsbygoogle' in script_tag['src']:
            script_tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and 'Google AdSense' in text):
        comment.extract()
        
    adsense_html = BeautifulSoup('\n<!-- Google AdSense -->\n<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-YOUR_ADSENSE_ID_HERE" crossorigin="anonymous"></script>\n', 'html.parser')
    head.append(adsense_html)

    # 7. Inject base styles for layout and buttons
    style_tag = soup.new_tag('style')
    style_tag.string = """
/* Base document styles for readability */
body {
    max-width: 1024px;
    margin: 0 auto;
    padding: 1em;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    line-height: 1.6;
    color: #333;
    word-wrap: break-word;
}
img {
    max-width: 100%;
    height: auto;
}
.nav-buttons {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 16px;
    margin: 24px 0;
}
.nav-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 8px 12px;
    width: 120px;
    box-sizing: border-box;
    background-color: transparent;
    color: #0b192c;
    text-decoration: none;
    border-radius: 8px;
    font-weight: 500;
    font-size: 0.9rem;
    border: 1px solid #0b192c;
    transition: all 0.2s ease;
    text-align: center;
    line-height: 1.4;
}
.nav-btn:hover {
    background-color: rgba(11, 25, 44, 0.05);
}
.nav-logo {
    width: 40px;
    height: 40px;
    object-fit: contain;
    border-radius: 8px;
}
@media screen and (max-width: 600px) {
    .nav-buttons {
        flex-direction: column;
        padding: 0 16px;
    }
}
"""
    head.append(style_tag)

    # 8. Inject Navigation Buttons into Body
    if body:
        # Remove old nav buttons to avoid duplicates if run multiple times
        for old_nav in soup.find_all('div', class_='nav-buttons'):
            old_nav.decompose()
            
        nav_html = """
<div class="nav-buttons">
  <a href="/" class="nav-btn w-inline-block">
    <span>Go to Home</span>
    <span>(English)</span>
  </a>
  <img src="/images/webclip.png" class="nav-logo" alt="Logo" />
  <a href="/ko/" class="nav-btn w-inline-block">
    <span>한국어 홈으로</span>
    <span>(Korean)</span>
  </a>
</div>
"""
        nav_soup_top = BeautifulSoup(nav_html, 'html.parser')
        nav_soup_bottom = BeautifulSoup(nav_html, 'html.parser')
        
        # Insert at the very beginning of body
        body.insert(0, nav_soup_top)
        # Append at the very end of body
        body.append(nav_soup_bottom)

    cleaned_html = str(soup)
    
    # Save back to file
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_html)
        print(f"✅ Cleaned & Upgraded SEO/Nav: {filepath}")
        return True
    except Exception as e:
        print(f"❌ Failed to write {filepath}: {e}")
        return False

def process_path(target_path):
    if os.path.isfile(target_path):
        if target_path.endswith('.html'):
            clean_html(target_path)
        else:
            print(f"Skipping non-HTML file: {target_path}")
    elif os.path.isdir(target_path):
        html_files = glob.glob(os.path.join(target_path, '*.html'))
        if not html_files:
            print(f"No HTML files found in {target_path}")
            return
            
        for file in html_files:
            clean_html(file)
    else:
        print(f"Path does not exist: {target_path}")

if __name__ == "__main__":
    default_path = "public/case-archive"
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        target = os.path.join(project_root, default_path)
        
    process_path(target)
