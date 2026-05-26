import fs from 'fs';
import path from 'path';

const CATEGORY_INFO = [
  {
    slug: 'dummy-english-law-note',
    category: 'english-law',
    isCase: false,
    titleEn: 'Introduction to English Common Law System',
    titleKo: '영국 커먼로(Common Law) 체계 개관',
    descEn: 'An overview of the development, structure, and key characteristics of the English legal system.',
    descKo: '영국 법체계의 발전 과정, 구조 및 주요 특징에 대한 개관.',
    longTailKeywordsEn: ['Common Law', 'Precedent', 'Source of Law'],
    longTailKeywordsKo: ['커먼로', '선례구속력', '법원'],
    pubDate: '2026-05-10T20:00:00Z',
    views: 1050,
  },
  {
    slug: 'dummy-contract-law-note',
    category: 'contract-law',
    isCase: false,
    titleEn: 'Principles of Offer and Acceptance in Contract Formation',
    titleKo: '계약 성립에 있어서 청약과 승낙의 원칙',
    descEn: 'A detailed note on how contracts are legally formed through mutual assent under English law.',
    descKo: '영국법상 상호 합의를 통해 계약이 법적으로 성립하는 방식에 대한 상세 정리.',
    longTailKeywordsEn: ['Offer', 'Acceptance', 'Agreement'],
    longTailKeywordsKo: ['청약', '승낙', '합의'],
    pubDate: '2026-05-12T20:00:00Z',
    views: 850,
  },
  {
    slug: 'dummy-tort-law-note',
    category: 'tort-law',
    isCase: false,
    titleEn: 'The Duty of Care in the Law of Negligence',
    titleKo: '과실법상 주의의무(Duty of Care)의 원칙',
    descEn: 'Exploring the establishment of duty of care following landmark judicial developments.',
    descKo: '사법적 발전 과정을 거쳐 정립된 주의의무(duty of care)의 개념 탐구.',
    longTailKeywordsEn: ['Negligence', 'Duty of Care', 'Neighbor Principle'],
    longTailKeywordsKo: ['과실법', '주의의무', '이웃원칙'],
    pubDate: '2026-05-14T20:00:00Z',
    views: 1200,
  },
  {
    slug: 'dummy-public-law-note',
    category: 'public-law',
    isCase: false,
    titleEn: 'The Doctrine of Parliamentary Supremacy',
    titleKo: '의회주권(Parliamentary Supremacy)의 원칙',
    descEn: 'Analysis of the constitutional doctrine that positions Parliament as the supreme legal authority.',
    descKo: '의회를 최고 법적 권위로 규정하는 헌법적 원칙에 대한 분석.',
    longTailKeywordsEn: ['Supremacy', 'Parliament', 'Constitution'],
    longTailKeywordsKo: ['의회주권', '의회', '헌법'],
    pubDate: '2026-05-16T20:00:00Z',
    views: 940,
  },
  {
    slug: 'dummy-criminal-law-note',
    category: 'criminal-law',
    isCase: false,
    titleEn: 'Actus Reus and Mens Rea in Criminal Liability',
    titleKo: '형사 책임에 있어서 행위(Actus Reus)와 고의(Mens Rea)',
    descEn: 'Understanding the physical and mental elements required to establish criminal liability.',
    descKo: '형사 책임을 성립시키기 위해 필요한 신체적 요소와 정신적 요소의 이해.',
    longTailKeywordsEn: ['Actus Reus', 'Mens Rea', 'Liability'],
    longTailKeywordsKo: ['범죄행위', '범죄고의', '형사책임'],
    pubDate: '2026-05-18T20:00:00Z',
    views: 710,
  },
  {
    slug: 'dummy-equity-law-note',
    category: 'equity-law',
    isCase: false,
    titleEn: 'The Nature and Maxims of Equity',
    titleKo: '형평법(Equity)의 성질과 격언들',
    descEn: 'A study on how equity acts as a gloss on the common law and its guiding maxims.',
    descKo: '커먼로를 보완하는 형평법의 원리와 이를 이끄는 주요 격언들에 대한 연구.',
    longTailKeywordsEn: ['Trusts', 'Maxims', 'Equity'],
    longTailKeywordsKo: ['신탁법', '형평법격언', '형평법'],
    pubDate: '2026-05-20T20:00:00Z',
    views: 1100,
  },
  {
    slug: 'dummy-land-law-note',
    category: 'land-law',
    isCase: false,
    titleEn: 'Understanding Co-ownership in Land Law',
    titleKo: '토지법상 공동소유(Co-ownership)의 이해',
    descEn: 'An examination of joint tenancy and tenancy in common under English property law.',
    descKo: '영국 재산법상 합동소유(joint tenancy)와 공유(tenancy in common)의 비교 검토.',
    longTailKeywordsEn: ['Co-ownership', 'Tenancy', 'Property'],
    longTailKeywordsKo: ['공동소유', '점유', '재산법'],
    pubDate: '2026-05-22T20:00:00Z',
    views: 650,
  },
  {
    slug: 'dummy-contract-law-case',
    category: 'contract-law-cases',
    isCase: true,
    titleEn: 'Carlill v Carbolic Smoke Ball Company',
    titleKo: 'Carlill v Carbolic Smoke Ball Company',
    descEn: 'The landmark contract case defining unilateral contracts and offer to the world.',
    descKo: '일방계약 및 대인 청약의 법리를 확립한 기념비적인 계약법 판례.',
    citation: '[1893] 1 QB 256',
    court: 'Court of Appeal',
    claimant: 'Louisa Elizabeth Carlill',
    defendant: 'Carbolic Smoke Ball Company',
    courtLink: 'https://www.bailii.org/ew/cases/EWCA/Civ/1892/1.html',
    longTailKeywordsEn: ['Offer', 'Unilateral Contract', 'Smoke Ball'],
    longTailKeywordsKo: ['청약', '일방계약', '광고효력'],
    pubDate: '2026-05-25T20:00:00Z',
    views: 1500,
  },
  {
    slug: 'dummy-tort-law-case',
    category: 'tort-law-cases',
    isCase: true,
    titleEn: 'Donoghue v Stevenson',
    titleKo: 'Donoghue v Stevenson',
    descEn: 'The foundational case of modern negligence law and the neighbor principle.',
    descKo: '현대 과실법과 이웃 원칙(neighbor principle)을 확립한 초석이 되는 판례.',
    citation: '[1932] AC 562',
    court: 'House of Lords',
    claimant: 'May Donoghue',
    defendant: 'David Stevenson',
    courtLink: 'https://www.bailii.org/uk/cases/UKHL/1932/100.html',
    longTailKeywordsEn: ['Negligence', 'Neighbor Principle', 'Duty of Care'],
    longTailKeywordsKo: ['과실법', '이웃원칙', '주의의무'],
    pubDate: '2026-05-24T20:00:00Z',
    views: 1800,
  },
  {
    slug: 'dummy-public-law-case',
    category: 'public-law-cases',
    isCase: true,
    titleEn: 'Entick v Carrington',
    titleKo: 'Entick v Carrington',
    descEn: 'A leading constitutional law case establishing civil liberties and limits on executive power.',
    descKo: '시민의 자유와 집행부 권력의 한계를 정립한 대표적인 헌법적 판례.',
    citation: '[1765] EWHC KB J98',
    court: 'Court of Common Pleas',
    claimant: 'John Entick',
    defendant: 'Nathan Carrington',
    courtLink: 'https://www.bailii.org/ew/cases/EWHC/KB/1765/J98.html',
    longTailKeywordsEn: ['Executive Power', 'Civil Liberties', 'Warrant'],
    longTailKeywordsKo: ['집행부권한', '시민자유', '영장주의'],
    pubDate: '2026-05-23T20:00:00Z',
    views: 750,
  },
  {
    slug: 'dummy-criminal-law-case',
    category: 'criminal-law-cases',
    isCase: true,
    titleEn: 'R v Woollin',
    titleKo: 'R v Woollin',
    descEn: 'A key criminal law case concerning indirect intention and murder.',
    descKo: '살인죄에 있어서 간접적 고의(indirect intention)를 규정한 주요 형사법 판례.',
    citation: '[1999] 1 AC 82',
    court: 'House of Lords',
    claimant: 'The Crown',
    defendant: 'Stephen Woollin',
    courtLink: 'https://www.bailii.org/uk/cases/UKHL/1998/28.html',
    longTailKeywordsEn: ['Murder', 'Intention', 'Indirect Intention'],
    longTailKeywordsKo: ['살인죄', '범죄고의', '간접고의'],
    pubDate: '2026-05-21T20:00:00Z',
    views: 920,
  },
  {
    slug: 'dummy-equity-law-case',
    category: 'equity-law-cases',
    isCase: true,
    titleEn: 'Milroy v Lord',
    titleKo: 'Milroy v Lord',
    descEn: 'The classic authority on the requirements for creating an effective trust.',
    descKo: '유효한 신탁(trust)을 설정하기 위한 요건을 다룬 대표적인 형평법 판례.',
    citation: '(1862) 4 DF & J 264',
    court: 'Court of Appeal in Chancery',
    claimant: 'Milroy',
    defendant: 'Lord',
    courtLink: 'https://www.bailii.org/ew/cases/EWHC/Ch/1862/J78.html',
    longTailKeywordsEn: ['Trusts', 'Declaration', 'Transfer'],
    longTailKeywordsKo: ['신탁법', '신탁선언', '재산양도'],
    pubDate: '2026-05-19T20:00:00Z',
    views: 680,
  },
  {
    slug: 'dummy-land-law-case',
    category: 'land-law-cases',
    isCase: true,
    titleEn: 'Street v Mountford',
    titleKo: 'Street v Mountford',
    descEn: 'The leading case defining the distinction between a lease and a licence.',
    descKo: '임대차(lease)와 사용허가(licence)의 구별 기준을 제시한 대표적인 토지법 판례.',
    citation: '[1985] AC 809',
    court: 'House of Lords',
    claimant: 'Roger Street',
    defendant: 'Wendy Mountford',
    courtLink: 'https://www.bailii.org/uk/cases/UKHL/1985/4.html',
    longTailKeywordsEn: ['Lease', 'Licence', 'Exclusive Possession'],
    longTailKeywordsKo: ['임대차', '사용허가', '독점적점유'],
    pubDate: '2026-05-17T20:00:00Z',
    views: 1350,
  },
];

const EN_DIR = path.resolve(import.meta.dirname || process.cwd(), '../src/content/posts/en/_dummies');
const KO_DIR = path.resolve(import.meta.dirname || process.cwd(), '../src/content/posts/ko/_dummies');

// Create directories if they don't exist
fs.mkdirSync(EN_DIR, { recursive: true });
fs.mkdirSync(KO_DIR, { recursive: true });

function getFrontmatter(item: typeof CATEGORY_INFO[0], lang: 'en' | 'ko'): string {
  const isEn = lang === 'en';
  const title = isEn ? item.titleEn : item.titleKo;
  const desc = isEn ? item.descEn : item.descKo;
  const keywords = isEn ? item.longTailKeywordsEn : item.longTailKeywordsKo;

  let fm = `---
lang: ${lang}
title: "${title}"
description: "${desc}"
slug: "${item.slug}"
category: "${item.category}"
pubDate: ${item.pubDate}
views: ${item.views}
isDummy: true
longTailKeywords:
`;

  keywords.forEach(k => {
    fm += `  - "${k}"\n`;
  });

  if (item.isCase) {
    fm += `citation: "${item.citation}"
court: "${item.court}"
claimant: "${item.claimant}"
defendant: "${item.defendant}"
courtLink: "${item.courtLink}"
`;
  }

  fm += `---
`;
  return fm;
}

function getBodyEn(item: typeof CATEGORY_INFO[0]): string {
  if (item.isCase) {
    return `
## Introduction

This is a dummy case review for **${item.titleEn}** with citation **${item.citation}**. Under English law, this case serves as a fundamental benchmark for study and examination purposes.

## Case Facts

The dispute arose in the context of commercial transactions and statements made by the parties. The claimant argued that a binding agreement had been established, whereas the defendant contended that the communication was merely an invitation to treat (ITT) or lacked consideration. The case went through multiple appeals before reaching the final judgment.

## Held

The court held that the parties' actions constituted a clear offer and acceptance. The judges laid down the following principles:
- An offer made to the public can become a binding contract upon compliance with its terms.
- Performance of the conditions in an advertisement is sufficient acceptance without notification.
- The arguments regarding intent were evaluated based on objective indicators.

## Ratio Decidendi

The core legal reasoning behind the decision was that objective indicators of intent take precedence over subjective mental states. The court clarified that advertising promises containing specific claims and deposits of sincerity constitute binding offers.

## Obiter Dicta

In passing, the judges commented on hypothetical scenarios where performance might be incomplete, suggesting that substantial performance could protect a performing party's interests in similar unilateral contexts.
`;
  } else {
    return `
## Key Concepts

This dummy lecture note discusses the fundamental theories of **${item.titleEn}**. It is designed for LLB, GDL, and SQE students seeking a structured revision pathway.

## Detailed Principles

Under English law, the subject is governed by a combination of common law jurisprudence and statutory modifications. To fully appreciate the doctrine, one must examine:
1. Historical development of the rules.
2. The modern judicial approach to interpreting these rights.
3. Policy considerations that influence judicial decision-making.

Furthermore, academic consensus suggests that reform is necessary to address inconsistencies in how courts balance commercial freedom against social fairness.

## Conclusion

Understanding these dynamics is vital for answering exam questions and solving problem scenarios. Students should practice applying these tests to factual patterns.
`;
  }
}

function getBodyKo(item: typeof CATEGORY_INFO[0]): string {
  if (item.isCase) {
    return `
## Introduction

이 글은 **${item.titleKo}** (${item.citation}) 판례에 대한 분석이다. 영국 커먼로 체계에서 본 판례는 법학 교육 및 실무의 핵심적 이정표 역할을 수행한다.

## Case Facts

당사자 간의 상업적 거래 및 의사 표시 과정에서 분쟁이 발생하였다. 원고는 유효한 구속력 있는 계약이 성립하였다고 주장한 반면, 피고는 해당 의사 표시가 단순한 청약의 유인(invitation to treat)에 불과하거나 약인(consideration)이 결여되어 계약이 성립하지 않았다고 항변하였다. 본 사안은 여러 심급을 거쳐 최종 판결에 이르렀다.

## Held

법원은 당사자의 행위가 명확한 청약과 승낙을 구성한다고 판시하였다. 법관들이 정립한 핵심 원칙은 다음과 같다:
- 대중을 상대로 이루어진 청약은 그 조건을 충족함으로써 구속력 있는 계약이 될 수 있다.
- 제시된 조건을 수행하는 것 자체로 승낙이 성립하며 별도의 통지는 요하지 않는다.
- 당사자의 법적 구속력 의사는 객관적 지표를 기준으로 평가된다.

## Ratio Decidendi

본 판결의 핵심적인 법적 근거(Ratio Decidendi)는 주관적 내심의 의사보다는 객관적인 행위를 통해 표현된 의사가 우선한다는 점입니다. 법원은 구체적인 보증이나 이행 진정성을 표시하는 예치금 등의 행위가 동반된 광고는 구속력 있는 청약을 구성한다고 판시했습니다.

## Obiter Dicta

사법부는 방론(Obiter Dicta)으로서 만약 이행 과정이 불완전했을 경우 발생할 수 있는 가설적 시나리오를 논의하며, 일방계약 체계에서 이행 행위에 착수한 당사자의 신뢰 이익이 보호받아야 할 필요성을 시사했습니다.
`;
  } else {
    return `
## 주요 개념 (Key Concepts)

본 요약 노트는 **${item.titleKo}**의 기본적인 이론들을 다룬다. GDL 및 SQE를 준비하는 학생들을 위한 체계적인 학습 자료로 기획되었다.

## 세부 원칙 (Detailed Principles)

영국법상 본 주제는 커먼로 판례 법리와 성문법적 수정 사항이 결합되어 규율된다. 해당 원칙을 완벽히 이해하기 위해서는 다음 사항을 검토해야 한다:
1. 규칙들의 역사적 발전 과정.
2. 해당 권리를 해석하는 현대 사법부의 접근 방식.
3. 법관의 의사 결정에 영향을 미치는 정책적 고려 사항.

나아가 학계에서는 사법부가 상업적 자유와 사회적 형평성 사이의 균형을 도모하는 과정에서 나타나는 불일치를 해결하기 위한 개혁이 필요하다는 지적이 제기되고 있다.

## 결론 (Conclusion)

이러한 사법적 동학을 이해하는 것은 시험 문제를 해결하고 실제 법률 분쟁 시나리오를 분석하는 데 있어 필수적이다. 학습자는 구체적 사실관계에 이 기준을 적용하는 연습을 반복해야 한다.
`;
  }
}

// Generate the files
for (const item of CATEGORY_INFO) {
  const enFm = getFrontmatter(item, 'en');
  const enBody = getBodyEn(item);
  fs.writeFileSync(path.join(EN_DIR, `${item.slug}.md`), enFm + enBody, 'utf8');

  const koFm = getFrontmatter(item, 'ko');
  const koBody = getBodyKo(item);
  fs.writeFileSync(path.join(KO_DIR, `${item.slug}.md`), koFm + koBody, 'utf8');
}

console.log('Dummy content seeded successfully.');
