import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';

const DEFAULT_TARGETS = [
  {
    company_id: null,
    company: 'Brain Corp',
    domain: 'braincorp.com',
    target_roles: 'CTO; Founder; Head of Talent; VP Engineering',
    reason_to_write: 'Generic job board detected for braincorp.com.',
    evidence_urls: 'https://www.braincorp.com/careers',
    score: 39,
  },
];

const BASE_PATHS = [
  '/',
  '/about',
  '/about-us',
  '/company',
  '/team',
  '/leadership',
  '/people',
  '/management',
  '/executive-team',
  '/contact',
  '/contact-us',
  '/careers',
];

const LINK_HINTS = [
  'about',
  'team',
  'leadership',
  'people',
  'management',
  'executive',
  'founder',
  'contact',
  'career',
  'company',
];

const GENERIC_EMAIL_LOCAL_PARTS = new Set([
  'admin',
  'billing',
  'careers',
  'contact',
  'employment',
  'hello',
  'help',
  'hi',
  'hiring',
  'hr',
  'info',
  'jobs',
  'legal',
  'media',
  'membership',
  'office',
  'press',
  'privacy',
  'recruiting',
  'sales',
  'security',
  'support',
  'team',
  'talent',
]);

const APPROVABLE_GENERIC_EMAIL_LOCAL_PARTS = new Set([
  'careers',
  'contact',
  'employment',
  'hello',
  'hi',
  'hiring',
  'hr',
  'jobs',
  'recruiting',
  'talent',
  'team',
]);

const GENERIC_EMAIL_SUBSTRINGS = [
  'career',
  'employ',
  'hiring',
  'recruit',
  'sales',
  'support',
  'talent',
];

const ROLE_PATTERNS = [
  /\b(co[-\s]?founder|founder)\b/i,
  /\b(chief executive officer|ceo)\b/i,
  /\b(chief technology officer|cto)\b/i,
  /\b(chief operating officer|coo)\b/i,
  /\b(vp engineering|vice president engineering|vice president of engineering)\b/i,
  /\b(head of engineering|engineering director|director of engineering)\b/i,
  /\b(head of product|vp product|vice president product|chief product officer)\b/i,
  /\b(head of operations|vp operations|vice president operations|operations director)\b/i,
  /\b(head of talent|vp talent|talent director)\b/i,
];

const EMAIL_RE = /(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi;
const PERSON_NAME_RE = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b/g;

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const targets = Array.isArray(input.targets) && input.targets.length
    ? input.targets
    : DEFAULT_TARGETS;
  const maxItems = Number(input.maxItems ?? 25);
  const maxPagesPerCompany = Number(input.maxPagesPerCompany ?? 12);
  const requestDelayMs = Number(input.requestDelayMs ?? 500);
  const requestTimeoutMs = Number(input.requestTimeoutMs ?? 10000);
  const includeGenericEmails = Boolean(input.includeGenericEmails ?? false);
  const includeExternalEmails = Boolean(input.includeExternalEmails ?? false);
  const emitMissesToDataset = input.emitMissesToDataset !== false;

  log.info('Starting contact candidate enrichment', {
    targetCount: targets.length,
    maxItems,
    maxPagesPerCompany,
  });

  let candidatesOutput = 0;
  let missesOutput = 0;

  for (const rawTarget of targets.slice(0, maxItems)) {
    const target = normalizeTarget(rawTarget);
    if (!target.domain) {
      const miss = missRecord(target, 'invalid_domain', []);
      missesOutput += 1;
      if (emitMissesToDataset) await Actor.pushData(miss);
      continue;
    }

    const result = await scanTarget(target, {
      maxPagesPerCompany,
      requestTimeoutMs,
      includeGenericEmails,
      includeExternalEmails,
    });

    if (result.candidates.length) {
      candidatesOutput += result.candidates.length;
      await Actor.pushData(result.candidates);
    } else {
      missesOutput += 1;
      if (emitMissesToDataset) {
        await Actor.pushData(missRecord(target, 'no_contact_candidate_found', result.checkedUrls));
      }
    }

    await Actor.setValue('STATE', {
      lastDomain: target.domain,
      candidatesOutput,
      missesOutput,
    });
    await sleep(requestDelayMs);
  }

  log.info('Contact candidate enrichment finished', {
    candidatesOutput,
    missesOutput,
  });
});

async function scanTarget(target, options) {
  const checkedUrls = [];
  const pages = [];
  const homepageUrl = `https://${target.domain}/`;
  const homepage = await fetchPage(homepageUrl, options.requestTimeoutMs);
  checkedUrls.push(homepageUrl);
  if (homepage.ok) pages.push(homepage);

  const candidateUrls = pageCandidates(target.domain, homepage.html, options.maxPagesPerCompany);
  for (const url of candidateUrls) {
    if (checkedUrls.includes(url)) continue;
    checkedUrls.push(url);
    const page = await fetchPage(url, options.requestTimeoutMs);
    if (page.ok) pages.push(page);
  }

  const candidates = [];
  for (const page of pages) {
    candidates.push(...extractCandidates(target, page, options));
  }

  return {
    checkedUrls,
    candidates: dedupeCandidates(candidates),
  };
}

function pageCandidates(domain, homepageHtml, maxPagesPerCompany) {
  const candidates = new Set(BASE_PATHS.map((path) => `https://${domain}${path}`));
  if (!homepageHtml) return [...candidates].slice(0, maxPagesPerCompany);

  const $ = cheerio.load(homepageHtml);
  $('a[href]').each((_index, element) => {
    const href = $(element).attr('href');
    const text = $(element).text().toLowerCase();
    const absoluteUrl = normalizeAbsoluteUrl(href, `https://${domain}/`);
    if (!absoluteUrl) return;

    let url;
    try {
      url = new URL(absoluteUrl);
    } catch {
      return;
    }
    if (!sameRegistrableHost(url.hostname, domain)) return;

    const haystack = `${text} ${url.pathname}`.toLowerCase();
    if (LINK_HINTS.some((hint) => haystack.includes(hint))) {
      candidates.add(url.toString());
    }
  });

  return [...candidates].slice(0, maxPagesPerCompany);
}

function extractCandidates(target, page, options) {
  const text = textFromHtml(page.html);
  const lines = textLines(text);
  const candidates = [];

  for (const email of extractMailtoEmails(page.html)) {
    if (!shouldKeepEmail(email, target.domain, options)) continue;
    const line = bestLineForEmail(lines, email);
    candidates.push(candidateRecord(target, {
      fullName: extractName(line, email),
      role: extractRole(line) || extractRole(textNearEmail(text, email)),
      email,
      sourceUrl: page.url,
      sourceExcerpt: line || textNearEmail(text, email),
      extraction: 'mailto_link',
    }));
  }

  for (const email of extractEmails(text)) {
    if (!shouldKeepEmail(email, target.domain, options)) continue;
    const line = bestLineForEmail(lines, email);
    const role = extractRole(line) || extractRole(textNearEmail(text, email));
    const fullName = extractName(line, email);
    candidates.push(candidateRecord(target, {
      fullName,
      role,
      email,
      sourceUrl: page.url,
      sourceExcerpt: line || textNearEmail(text, email),
      extraction: 'email_regex',
    }));
  }

  for (const line of lines) {
    const role = extractRole(line);
    if (!role) continue;
    const email = firstEmail(line);
    if (email && !shouldKeepEmail(email, target.domain, options)) continue;
    const fullName = extractName(line, email);
    if (!fullName || !email) continue;
    candidates.push(candidateRecord(target, {
      fullName,
      role,
      email,
      sourceUrl: page.url,
      sourceExcerpt: line,
      extraction: 'role_line_with_email',
    }));
  }

  return candidates;
}

function candidateRecord(target, details) {
  const emailClassification = classifyEmail(details.email, target.domain);
  const hasNameEvidence = Boolean(details.fullName);
  const hasRoleEvidence = Boolean(details.role);
  const reviewHint = reviewHintFor({
    emailClassification,
    hasNameEvidence,
    hasRoleEvidence,
    extraction: details.extraction,
  });

  return {
    record_type: 'contact_candidate',
    review_status: 'needs_review',
    recommended_review_status: reviewHint.recommendedStatus,
    review_hint: reviewHint.hint,
    candidate_type: emailClassification.candidateType,
    is_generic_email: emailClassification.isGenericEmail,
    is_company_domain_email: emailClassification.isCompanyDomainEmail,
    has_name_evidence: hasNameEvidence,
    has_role_evidence: hasRoleEvidence,
    company_id: target.company_id,
    company_domain: target.domain,
    company: target.company,
    target_roles: target.target_roles,
    full_name: details.fullName || '',
    role: details.role || '',
    email: details.email,
    source_type: 'manual_review',
    source_url: details.sourceUrl,
    provider_name: 'apify-contact-candidate-enricher',
    verification_status: 'manual_verified',
    confidence: confidenceFor(details),
    reason_to_write: target.reason_to_write,
    evidence_urls: target.evidence_urls,
    score: target.score,
    source_excerpt: compactWhitespace(details.sourceExcerpt || '').slice(0, 500),
    extraction: details.extraction,
  };
}

function missRecord(target, reason, checkedUrls) {
  return {
    record_type: 'miss',
    reason,
    company_id: target.company_id,
    company_domain: target.domain,
    company: target.company,
    score: target.score,
    checked_urls: checkedUrls.join(';'),
  };
}

async function fetchPage(url, requestTimeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: controller.signal,
      headers: {
        'user-agent': 'VoidRadarContactCandidateEnricher/0.1 (+https://apify.com)',
        accept: 'text/html,text/plain;q=0.9,*/*;q=0.1',
      },
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html') && !contentType.includes('text/plain')) {
      return { ok: false, url, status: response.status, html: '' };
    }
    const html = await response.text();
    return {
      ok: response.ok,
      url: response.url || url,
      status: response.status,
      html,
    };
  } catch (error) {
    log.debug('Page fetch failed', { url, error: error.message });
    return { ok: false, url, status: null, html: '' };
  } finally {
    clearTimeout(timeout);
  }
}

function normalizeTarget(rawTarget) {
  return {
    company_id: clean(rawTarget.company_id ?? rawTarget.companyId),
    company: clean(rawTarget.company),
    domain: normalizeDomain(rawTarget.domain ?? rawTarget.company_domain ?? rawTarget.website),
    target_roles: clean(rawTarget.target_roles),
    reason_to_write: clean(rawTarget.reason_to_write),
    evidence_urls: clean(rawTarget.evidence_urls),
    score: rawTarget.score ?? '',
  };
}

function normalizeDomain(value) {
  const raw = clean(value).toLowerCase();
  if (!raw) return null;
  try {
    const parsed = new URL(raw.startsWith('http') ? raw : `https://${raw}`);
    return parsed.hostname.replace(/^www\./, '');
  } catch {
    return raw.replace(/^www\./, '').replace(/\/.*$/, '') || null;
  }
}

function normalizeAbsoluteUrl(value, baseUrl) {
  if (!value || value.startsWith('mailto:') || value.startsWith('tel:')) return null;
  try {
    return new URL(value, baseUrl).toString();
  } catch {
    return null;
  }
}

function sameRegistrableHost(hostname, domain) {
  const host = hostname.replace(/^www\./, '').toLowerCase();
  const normalizedDomain = domain.replace(/^www\./, '').toLowerCase();
  return host === normalizedDomain || host.endsWith(`.${normalizedDomain}`);
}

function textFromHtml(html) {
  const $ = cheerio.load(html);
  $('script, style, noscript, svg').remove();
  $('br, p, div, section, article, li, tr, h1, h2, h3, h4, h5, h6, a').append('\n');
  return $('body').text() || $.root().text();
}

function textLines(value) {
  return value
    .split(/\n+/)
    .map((line) => compactWhitespace(line))
    .filter((line) => line.length >= 5 && line.length <= 260);
}

function extractEmails(value) {
  return [...new Set([...value.matchAll(EMAIL_RE)].map((match) => match[1].toLowerCase()))];
}

function extractMailtoEmails(html) {
  const $ = cheerio.load(html);
  const emails = [];
  $('a[href^="mailto:"]').each((_index, element) => {
    const href = $(element).attr('href') || '';
    const email = decodeURIComponent(href.replace(/^mailto:/i, ''))
      .split(/[?;]/)[0]
      .trim()
      .toLowerCase();
    if (email && EMAIL_RE.test(email)) {
      emails.push(email);
    }
    EMAIL_RE.lastIndex = 0;
  });
  return [...new Set(emails)];
}

function firstEmail(value) {
  return extractEmails(value)[0] || null;
}

function shouldKeepEmail(email, domain, options) {
  const classification = classifyEmail(email, domain);
  const localPart = classification.localPart;
  const emailDomain = classification.emailDomain;
  if (!localPart || localPart.includes('%')) {
    return false;
  }
  if (!options.includeExternalEmails && emailDomain !== domain.toLowerCase()) {
    return false;
  }
  if (!options.includeGenericEmails && GENERIC_EMAIL_LOCAL_PARTS.has(localPart)) {
    return false;
  }
  if (!options.includeGenericEmails && localPart === domain.split('.')[0].toLowerCase()) {
    return false;
  }
  if (!options.includeGenericEmails && looksLikeConcatenatedGenericLocalPart(localPart)) {
    return false;
  }
  return true;
}

function classifyEmail(email, domain) {
  const [localPart = '', emailDomain = ''] = email.toLowerCase().split('@');
  const normalizedDomain = domain.toLowerCase();
  const isCompanyDomainEmail = emailDomain === normalizedDomain;
  const genericLocalPart = genericLocalPartFor(localPart);
  const isGenericEmail = Boolean(genericLocalPart);
  let candidateType = 'direct_person';
  if (!isCompanyDomainEmail) {
    candidateType = 'external_email';
  } else if (isGenericEmail) {
    candidateType = APPROVABLE_GENERIC_EMAIL_LOCAL_PARTS.has(genericLocalPart)
      ? 'generic_inbox'
      : 'low_value_generic_inbox';
  }
  return {
    localPart,
    emailDomain,
    isCompanyDomainEmail,
    isGenericEmail,
    candidateType,
  };
}

function genericLocalPartFor(localPart) {
  if (GENERIC_EMAIL_LOCAL_PARTS.has(localPart)) {
    return localPart;
  }
  const withoutTrailingDigits = localPart.replace(/\d+$/, '');
  if (GENERIC_EMAIL_LOCAL_PARTS.has(withoutTrailingDigits)) {
    return withoutTrailingDigits;
  }
  const substring = GENERIC_EMAIL_SUBSTRINGS.find((part) => localPart.includes(part));
  if (substring) {
    if (substring === 'career') return 'careers';
    if (substring === 'employ') return 'employment';
    if (substring === 'recruit') return 'recruiting';
    return substring;
  }
  return '';
}

function reviewHintFor({ emailClassification, hasNameEvidence, hasRoleEvidence, extraction }) {
  if (emailClassification.candidateType === 'external_email') {
    return {
      recommendedStatus: 'reject',
      hint: 'External-domain email. Approve only if the source proves this person represents the target company.',
    };
  }
  if (emailClassification.candidateType === 'low_value_generic_inbox') {
    return {
      recommendedStatus: 'reject',
      hint: 'Generic inbox with low outreach value.',
    };
  }
  if (emailClassification.candidateType === 'generic_inbox') {
    return {
      recommendedStatus: 'needs_review',
      hint: 'Generic company inbox. Use only as fallback when no named decision maker exists.',
    };
  }
  if (hasNameEvidence && hasRoleEvidence) {
    return {
      recommendedStatus: 'approve_candidate',
      hint: 'Named person with role evidence and direct company email.',
    };
  }
  if (hasRoleEvidence) {
    return {
      recommendedStatus: 'needs_review',
      hint: 'Role evidence found, but person name is missing.',
    };
  }
  if (extraction === 'mailto_link') {
    return {
      recommendedStatus: 'needs_review',
      hint: 'Direct company email from mailto link. Confirm it belongs to a useful person or team.',
    };
  }
  return {
    recommendedStatus: 'needs_review',
    hint: 'Direct company email found. Confirm source evidence before approving.',
  };
}

function looksLikeConcatenatedGenericLocalPart(localPart) {
  if (localPart.length < 14) {
    return false;
  }
  return [...GENERIC_EMAIL_LOCAL_PARTS].some((genericPart) => (
    localPart.includes(genericPart) && localPart !== genericPart
  ));
}

function bestLineForEmail(lines, email) {
  return lines.find((line) => line.toLowerCase().includes(email.toLowerCase())) || '';
}

function textNearEmail(text, email) {
  const index = text.toLowerCase().indexOf(email.toLowerCase());
  if (index < 0) return '';
  return compactWhitespace(text.slice(Math.max(0, index - 180), index + 220));
}

function extractRole(value) {
  for (const pattern of ROLE_PATTERNS) {
    const match = value.match(pattern);
    if (match) return normalizeRole(match[1]);
  }
  return '';
}

function normalizeRole(value) {
  const normalized = compactWhitespace(value).toLowerCase();
  const replacements = {
    ceo: 'CEO',
    cto: 'CTO',
    coo: 'COO',
    founder: 'Founder',
    'co-founder': 'Co-Founder',
    'co founder': 'Co-Founder',
    'chief executive officer': 'Chief Executive Officer',
    'chief technology officer': 'Chief Technology Officer',
    'chief operating officer': 'Chief Operating Officer',
  };
  if (replacements[normalized]) return replacements[normalized];
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function extractName(line, email) {
  const withoutEmail = email ? line.replace(email, ' ') : line;
  const matches = [...withoutEmail.matchAll(PERSON_NAME_RE)].map((match) => match[1]);
  const filtered = matches.filter((name) => isLikelyPersonName(name));
  return filtered[0] || '';
}

function isLikelyPersonName(value) {
  const blocked = new Set(['Chief Technology', 'Chief Executive', 'Vice President', 'Head Of']);
  if (blocked.has(value)) return false;
  const words = value.split(/\s+/);
  return words.length >= 2 && words.length <= 4;
}

function confidenceFor(details) {
  if (details.fullName && details.role && details.email) return 0.9;
  if (details.role && details.email) return 0.82;
  return 0.72;
}

function dedupeCandidates(candidates) {
  const seen = new Set();
  const unique = [];
  for (const candidate of candidates) {
    const key = `${candidate.company_domain}|${candidate.email}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(candidate);
  }
  return unique;
}

function compactWhitespace(value) {
  return clean(value).replace(/\s+/g, ' ').trim();
}

function clean(value) {
  return String(value ?? '').trim();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
