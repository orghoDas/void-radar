import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';
import { createHash } from 'node:crypto';

const DEFAULT_TARGETS = [
  {
    company_id: null,
    company: 'Example AI',
    domain: 'example.ai',
    reason_to_write: 'Example AI posted a current hiring signal.',
    evidence_urls: 'https://news.ycombinator.com/item?id=1',
    score: 34,
  },
];

const BASE_PATHS = [
  '/',
  '/about',
  '/about-us',
  '/product',
  '/products',
  '/pricing',
  '/customers',
  '/case-studies',
  '/careers',
  '/blog',
  '/news',
  '/team',
  '/contact',
  '/contact-us',
];

const LINK_HINTS = [
  'about',
  'product',
  'pricing',
  'customer',
  'case',
  'career',
  'blog',
  'news',
  'team',
  'contact',
  'company',
];

const TECH_TERMS = [
  'ai',
  'api',
  'automation',
  'aws',
  'azure',
  'cloud',
  'data',
  'developer',
  'devops',
  'gcp',
  'integration',
  'kubernetes',
  'machine learning',
  'postgres',
  'python',
  'react',
  'salesforce',
  'security',
  'slack',
  'typescript',
  'workflow',
];

const CUSTOMER_TERMS = [
  'b2b',
  'businesses',
  'customers',
  'developers',
  'enterprise',
  'founders',
  'healthcare',
  'logistics',
  'marketplaces',
  'operations',
  'product teams',
  'sales teams',
  'startups',
];

const BUSINESS_MODEL_TERMS = [
  'annual',
  'api',
  'book a demo',
  'demo',
  'enterprise',
  'free trial',
  'platform',
  'pricing',
  'request access',
  'saas',
  'self serve',
  'subscription',
];

const SERVICE_FIT_TERMS = [
  'automation',
  'backlog',
  'dashboard',
  'data pipeline',
  'hiring',
  'integration',
  'manual',
  'migration',
  'operations',
  'platform',
  'scaling',
  'workflow',
];

const ROLE_RE = /\b(Founder|Co-Founder|CEO|Chief Executive Officer|CTO|Chief Technology Officer|VP Engineering|Head of Engineering|Head of Product|COO|Head of Operations)\b/i;
const PERSON_NAME_RE = /\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b/g;
const EMAIL_RE = /(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi;

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const targets = Array.isArray(input.targets) && input.targets.length
    ? input.targets
    : DEFAULT_TARGETS;
  const maxItems = Number(input.maxItems ?? 10);
  const maxPagesPerCompany = Number(input.maxPagesPerCompany ?? 10);
  const requestDelayMs = Number(input.requestDelayMs ?? 500);
  const requestTimeoutMs = Number(input.requestTimeoutMs ?? 10000);
  const includePageText = input.includePageText !== false;
  const emitPageRecords = input.emitPageRecords !== false;

  log.info('Starting company research', {
    targetCount: targets.length,
    maxItems,
    maxPagesPerCompany,
    includePageText,
    emitPageRecords,
  });

  let companiesOutput = 0;
  let pageRecordsOutput = 0;

  for (const rawTarget of targets.slice(0, maxItems)) {
    const target = normalizeTarget(rawTarget);
    if (!target.domain) {
      await Actor.pushData(companyResearchRecord(target, [], ['invalid_domain'], includePageText));
      companiesOutput += 1;
      continue;
    }

    const pages = await researchTarget(target, {
      maxPagesPerCompany,
      requestTimeoutMs,
      includePageText,
    });
    const record = companyResearchRecord(target, pages, [], includePageText);
    await Actor.pushData(record);
    companiesOutput += 1;

    if (emitPageRecords && pages.length) {
      const pageRecords = pages.map((page) => pageResearchRecord(target, page, includePageText));
      await Actor.pushData(pageRecords);
      pageRecordsOutput += pageRecords.length;
    }

    await Actor.setValue('STATE', {
      lastDomain: target.domain,
      companiesOutput,
      pageRecordsOutput,
    });
    await sleep(requestDelayMs);
  }

  log.info('Company research finished', {
    companiesOutput,
    pageRecordsOutput,
  });
});

async function researchTarget(target, options) {
  const homepageUrl = `https://${target.domain}/`;
  const homepage = await fetchPage(homepageUrl, options.requestTimeoutMs);
  const candidateUrls = pageCandidates(
    target.domain,
    homepage.ok ? homepage.html : '',
    options.maxPagesPerCompany,
  );

  const pages = [];
  const checked = new Set();
  if (homepage.ok) {
    pages.push(pageFacts(homepage, options.includePageText));
    checked.add(homepageUrl);
  }

  for (const url of candidateUrls) {
    if (checked.has(url)) continue;
    checked.add(url);
    const page = await fetchPage(url, options.requestTimeoutMs);
    if (page.ok) {
      pages.push(pageFacts(page, options.includePageText));
    }
    if (pages.length >= options.maxPagesPerCompany) break;
  }
  return pages;
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

async function fetchPage(url, requestTimeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: controller.signal,
      headers: {
        'user-agent': 'VoidRadarCompanyResearcher/0.1 (+https://apify.com)',
        accept: 'text/html,text/plain;q=0.9,*/*;q=0.1',
      },
    });
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html') && !contentType.includes('text/plain')) {
      return { ok: false, url, finalUrl: response.url || url, status: response.status, html: '' };
    }
    const html = await response.text();
    return {
      ok: response.ok,
      url,
      finalUrl: response.url || url,
      status: response.status,
      contentType,
      html,
    };
  } catch (error) {
    log.debug('Page fetch failed', { url, error: error.message });
    return { ok: false, url, finalUrl: url, status: null, html: '' };
  } finally {
    clearTimeout(timeout);
  }
}

function pageFacts(page, includePageText) {
  const $ = cheerio.load(page.html);
  const title = compactWhitespace($('title').first().text());
  const metaDescription = compactWhitespace(
    $('meta[name="description"]').attr('content')
      || $('meta[property="og:description"]').attr('content')
      || '',
  );
  const h1 = compactWhitespace($('h1').first().text());
  const text = textFromHtml(page.html);
  const lines = textLines(text);

  return {
    url: page.url,
    final_url: page.finalUrl,
    status_code: page.status,
    content_type: page.contentType,
    title,
    meta_description: metaDescription,
    h1,
    text_sample: compactWhitespace(text).slice(0, 1200),
    page_text: includePageText ? compactWhitespace(text).slice(0, 20000) : '',
    content_hash: sha256(compactWhitespace(text)),
    technology_mentions: matchedTerms(text, TECH_TERMS),
    customer_terms: matchedTerms(text, CUSTOMER_TERMS),
    business_model_terms: matchedTerms(text, BUSINESS_MODEL_TERMS),
    service_fit_snippets: snippetsForTerms(lines, SERVICE_FIT_TERMS, 5),
    contact_routes: contactRoutes(page.finalUrl, page.html, lines),
    decision_maker_names: decisionMakerNames(lines),
  };
}

function companyResearchRecord(target, pages, reasons, includePageText) {
  const allText = pages.map((page) => page.page_text || page.text_sample).join(' ');
  const positioning = firstNonEmpty(
    pages.map((page) => page.meta_description || page.h1 || page.title),
  );
  return {
    record_type: 'company_research',
    company_id: target.company_id,
    company: target.company,
    domain: target.domain,
    contact_id: target.contact_id,
    contact_email: target.contact_email,
    score: target.score,
    reason_to_write: target.reason_to_write,
    evidence_urls: target.evidence_urls,
    page_count: pages.length,
    checked_urls: pages.map((page) => page.final_url).join(';'),
    positioning,
    business_model_terms: uniqueFlat(pages.map((page) => page.business_model_terms)),
    customer_terms: uniqueFlat(pages.map((page) => page.customer_terms)),
    technology_mentions: uniqueFlat(pages.map((page) => page.technology_mentions)),
    service_fit_evidence: uniqueFlat(pages.map((page) => page.service_fit_snippets)).slice(0, 10),
    contact_routes: uniqueContactRoutes(pages.flatMap((page) => page.contact_routes)).slice(0, 20),
    decision_maker_names: uniqueFlat(pages.map((page) => page.decision_maker_names)).slice(0, 20),
    research_summary: researchSummary({ target, positioning, allText, pages }),
    page_records: pages.map((page) => scrubPageForSummary(page, includePageText)),
    reasons,
  };
}

function pageResearchRecord(target, page, includePageText) {
  return {
    record_type: 'page_research',
    company_id: target.company_id,
    company: target.company,
    domain: target.domain,
    url: page.url,
    final_url: page.final_url,
    status_code: page.status_code,
    content_type: page.content_type,
    title: page.title,
    h1: page.h1,
    meta_description: page.meta_description,
    text_sample: page.text_sample,
    page_text: includePageText ? page.page_text : '',
    content_hash: page.content_hash,
  };
}

function scrubPageForSummary(page, includePageText) {
  return {
    ...page,
    page_text: includePageText ? page.page_text : '',
  };
}

function researchSummary({ target, positioning, allText, pages }) {
  const text = allText.toLowerCase();
  const bits = [];
  if (positioning) bits.push(positioning);
  if (text.includes('api') || text.includes('developer')) {
    bits.push('Developer/API surface detected.');
  }
  if (text.includes('automation') || text.includes('workflow')) {
    bits.push('Automation or workflow language detected.');
  }
  if (pages.some((page) => /career|job/i.test(page.final_url))) {
    bits.push('Careers content is visible.');
  }
  if (target.reason_to_write) {
    bits.push(`Trigger: ${target.reason_to_write}`);
  }
  return bits.join(' ');
}

function contactRoutes(finalUrl, html, lines) {
  const $ = cheerio.load(html);
  const routes = [];
  if (/contact|career|job/i.test(finalUrl)) {
    routes.push({ route_type: 'page', value: finalUrl });
  }
  $('a[href^="mailto:"]').each((_index, element) => {
    const href = $(element).attr('href') || '';
    const email = decodeURIComponent(href.replace(/^mailto:/i, ''))
      .split(/[?;]/)[0]
      .trim()
      .toLowerCase();
    if (email && EMAIL_RE.test(email)) {
      routes.push({ route_type: 'mailto', value: email, source_url: finalUrl });
    }
    EMAIL_RE.lastIndex = 0;
  });
  for (const line of lines) {
    for (const email of extractEmails(line)) {
      routes.push({ route_type: 'email_text', value: email, source_url: finalUrl });
    }
  }
  return routes;
}

function decisionMakerNames(lines) {
  const names = [];
  for (const line of lines) {
    if (!ROLE_RE.test(line)) continue;
    const matches = [...line.matchAll(PERSON_NAME_RE)].map((match) => match[1]);
    for (const name of matches) {
      if (isLikelyPersonName(name)) {
        names.push(`${name} - ${normalizeRole(line.match(ROLE_RE)?.[1] || '')}`.trim());
      }
    }
  }
  return [...new Set(names)];
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
    .filter((line) => line.length >= 5 && line.length <= 320);
}

function snippetsForTerms(lines, terms, limit) {
  const snippets = [];
  for (const line of lines) {
    const lowered = line.toLowerCase();
    if (terms.some((term) => lowered.includes(term))) {
      snippets.push(line);
    }
    if (snippets.length >= limit) break;
  }
  return [...new Set(snippets)];
}

function matchedTerms(text, terms) {
  const lowered = text.toLowerCase();
  return terms.filter((term) => lowered.includes(term));
}

function extractEmails(value) {
  return [...new Set([...value.matchAll(EMAIL_RE)].map((match) => match[1].toLowerCase()))];
}

function uniqueFlat(values) {
  return [...new Set(values.flat().filter(Boolean))];
}

function uniqueContactRoutes(routes) {
  const seen = new Set();
  const unique = [];
  for (const route of routes) {
    const key = `${route.route_type}|${route.value}|${route.source_url || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(route);
  }
  return unique;
}

function normalizeTarget(rawTarget) {
  return {
    company_id: clean(rawTarget.company_id ?? rawTarget.companyId),
    company: clean(rawTarget.company),
    domain: normalizeDomain(rawTarget.domain ?? rawTarget.company_domain ?? rawTarget.website),
    contact_id: clean(rawTarget.contact_id ?? rawTarget.contactId),
    contact_email: clean(rawTarget.contact_email ?? rawTarget.email),
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
  };
  if (replacements[normalized]) return replacements[normalized];
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function isLikelyPersonName(value) {
  const blocked = new Set(['Chief Technology', 'Chief Executive', 'Vice President', 'Head Of']);
  if (blocked.has(value)) return false;
  const words = value.split(/\s+/);
  return words.length >= 2 && words.length <= 4;
}

function firstNonEmpty(values) {
  return values.find((value) => clean(value)) || '';
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
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
