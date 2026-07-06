# Agent Rules

## Formatting Korean Text
- **Avoid Markdown Bold (`**`) for Korean Text**: When emphasizing or bolding Korean text, NEVER use Markdown's `**word**` syntax. This is because Korean postpositions (조사) immediately following the emphasized word cause Markdown parsers to fail (due to CommonMark right-flanking delimiter rules).
- **Use HTML `<strong>`**: ALWAYS use the HTML `<strong>word</strong>` tag instead. For example, use `<strong>약정(covenant)</strong>에` instead of `**약정(covenant)**에`.

## Natural Korean Translation
- **Avoid Unnatural Literal Translations & Invented Words**: Do NOT invent awkward, non-standard Hanja-based words (e.g., "신곡", "구곡", "비소송") or use overly academic translations that aren't used in everyday Korean (e.g., translating "equivocal" as "복의적"). Avoid Japanese-influenced or archaic literal translations like "~에 기한" or "~에 기하여" (based on/grounded on); use more natural expressions like "~에 기반하여", "~에 기초하여", or "~를 근거로" instead. Always use natural, commonly used Korean expressions. **CRITICAL: If you do not know the exact, widely accepted Korean legal equivalent for a specific English legal term, DO NOT guess or invent a new word. Leave it in its original English form.**
- **Avoid Archaic Legal Jargon**: Do NOT use outdated legal terms like "설시(하다)". Instead, depending on the context, use more natural alternatives such as "판시하다" (ruled/held), "지적하다" (pointed out), or "설명하다" (explained). Prioritize everyday Korean usage over forced literal translations while maintaining professional academic tone.
- **Omit Honorific Titles**: In academic/legal writing, do NOT translate titles like "Mr.", "Mrs.", or "Ms." into overly polite Korean equivalents like "여사", "선생", or "씨". Simply drop the title and use the person's name (e.g., "Mrs Carlill" -> "Carlill", or "Louisa Carlill").
- **Do Not Hallucinate Translations for Specific Civic/Historical Terms**: If an English term represents a specific UK historical or civic official/role (e.g., "swordbearer"), and there is no direct, widely accepted Korean equivalent, DO NOT invent a translation (e.g., "검도원장"). Leave the term in its original English form.
- **Translate "The Crown" as "정부"**: In legal and case law contexts, "The Crown" almost always refers to the government or executive branch acting on behalf of the monarch. Do NOT translate it as "왕실" (Royal Family/Court). Translate it as "정부".

## Internal Links in Korean Text
- **Use `/ko/` Prefix for Internal Links**: When linking to other case articles from within a Korean markdown file, you MUST prepend `/ko` to the slug. For example, use `[Fisher v Bell [1961]](/ko/fisher-v-bell)` instead of `[Fisher v Bell [1961]](/fisher-v-bell)`. Do not link to the English version from a Korean article unless explicitly requested.
