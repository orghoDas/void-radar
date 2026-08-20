import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';

const SOURCE = 'hacker_news_who_is_hiring';
const SOURCE_NAME = 'Hacker News Who is Hiring';
const ALGOLIA_BASE_URL = 'https://hn.algolia.com/api/v1';

// Prose fallback only runs when a comment links nothing. Sentence boundaries
// without a following space ("...our process.We are hiring") look exactly like
// hostnames, and ".we"/".you"/".no" are real TLDs, so this path accepts only
// suffixes that companies actually publish under.
const TEXT_FALLBACK_TLDS = new Set([
  'com', 'io', 'ai', 'dev', 'co', 'net', 'org', 'app', 'xyz', 'tech',
  'cloud', 'sh', 'so', 'fyi', 'health', 'earth', 'space', 'run', 'bot',
]);

const BLOCKED_DOMAINS = new Set([
  'ycombinator.com',
  'news.ycombinator.com',
  'github.com',
  'linkedin.com',
  'twitter.com',
  'x.com',
  'google.com',
  'docs.google.com',
  'forms.gle',
  'greenhouse.io',
  'lever.co',
  'ashbyhq.com',
  'workable.com',
  'notion.com',
  'app.notion.com',
  'typeform.com',
]);

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const maxItems = Number(input.maxItems ?? 100);
  const minCommentLength = Number(input.minCommentLength ?? 80);
  const query = input.query ?? 'Ask HN: Who is hiring?';
  const threadId = input.threadId || (await findLatestWhoIsHiringThread(query));

  if (!threadId) {
    throw new Error('Unable to find a Who is Hiring thread.');
  }

  log.info('Starting HN Who is Hiring discovery', {
    threadId,
    maxItems,
    minCommentLength,
  });

  const story = await fetchJson(`${ALGOLIA_BASE_URL}/items/${threadId}`);
  const comments = flattenComments(story.children || []);
  const records = [];

  for (const comment of comments) {
    if (records.length >= maxItems) {
      break;
    }

    const record = standardizeComment(comment, story, minCommentLength);
    if (record) {
      records.push(record);
    }
  }

  await Actor.pushData(records);
  await Actor.setValue('STATE', {
    threadId,
    commentsScanned: comments.length,
    recordsOutput: records.length,
  });

  log.info('HN Who is Hiring discovery finished', {
    threadId,
    commentsScanned: comments.length,
    recordsOutput: records.length,
  });
});

async function findLatestWhoIsHiringThread(query) {
  const url = new URL(`${ALGOLIA_BASE_URL}/search_by_date`);
  url.searchParams.set('tags', 'story');
  url.searchParams.set('query', query);
  url.searchParams.set('hitsPerPage', '10');

  const result = await fetchJson(url.toString());
  const hit = (result.hits || []).find((item) => {
    const title = String(item.title || '').toLowerCase();
    return title.startsWith('ask hn: who is hiring?');
  });
  return hit?.objectID || null;
}

function standardizeComment(comment, story, minCommentLength) {
  const html = comment.text || '';
  const plainText = htmlToText(html);
  if (plainText.length < minCommentLength) {
    return null;
  }

  const domain = extractCompanyDomain(html);
  const companyName = inferCompanyName(plainText, domain);
  if (!domain || !companyName) {
    return null;
  }

  const sourceUrl = `https://news.ycombinator.com/item?id=${comment.id}`;
  const eventDate = normalizeDate(comment.created_at || story.created_at);

  return {
    source: SOURCE,
    source_url: sourceUrl,
    source_record_id: String(comment.id),
    company_name: companyName,
    website: `https://${domain}`,
    domain,
    location: inferLocation(plainText),
    industry: null,
    stage: null,
    status: 'active',
    employee_count: null,
    description: plainText.slice(0, 2000),
    tags: ['hiring', 'hacker_news'],
    event_type: 'hiring',
    event_date: eventDate,
    event_summary: `${companyName} posted in ${story.title || 'HN Who is Hiring'}.`,
    raw_source_payload: {
      comment,
      story_id: story.id,
      story_title: story.title,
      source_name: SOURCE_NAME,
    },
  };
}

function flattenComments(comments) {
  return comments.flatMap((comment) => [
    comment,
    ...flattenComments(comment.children || []),
  ]);
}

function extractCompanyDomain(html) {
  const $ = cheerio.load(html || '');
  const candidates = $('a[href]')
    .toArray()
    .map((element) => normalizeDomain($(element).attr('href')))
    .filter((domain) => domain && !isBlockedDomain(domain));

  return candidates[0] || extractDomainFromText(htmlToText(html));
}

function extractDomainFromText(value) {
  const matches = String(value || '').match(/\b(?:https?:\/\/)?(?:www\.)?([a-z0-9-]+\.[a-z0-9.-]+)\b/gi) || [];
  for (const match of matches) {
    const domain = normalizeDomain(match);
    if (!domain || isBlockedDomain(domain)) {
      continue;
    }
    if (!TEXT_FALLBACK_TLDS.has(domain.split('.').pop())) {
      continue;
    }
    return domain;
  }
  return null;
}

function inferCompanyName(text, domain) {
  const firstLine = String(text || '').split(/\n|\|/)[0].trim();
  const cleaned = firstLine
    .replace(/https?:\/\/\S+/gi, ' ')
    .replace(/\bwww\.\S+/gi, ' ')
    .replace(/\s*\([^)]*\)\s*/g, ' ')
    .replace(/\s+-\s+.*$/g, '')
    .replace(/\s+is hiring.*$/i, '')
    .replace(/\s+hiring.*$/i, '')
    .replace(/[,:;.]+$/g, '')
    .trim();

  if (cleaned && cleaned.length <= 80) {
    return cleaned;
  }

  if (!domain) {
    return null;
  }

  return domain
    .split('.')[0]
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function inferLocation(text) {
  const match = String(text || '').match(/\b(remote|hybrid|onsite|on-site|new york|london|san francisco|berlin|paris|amsterdam)\b/i);
  return match ? match[0] : null;
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      accept: 'application/json',
      'user-agent': 'VoidRadarHNWhoIsHiringDiscovery/0.1 (+mailto:hello@voidstudio.tech)',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }

  return response.json();
}

function htmlToText(html) {
  const $ = cheerio.load(html || '');
  $('p').append('\n');
  return $.text().replace(/\s+\n/g, '\n').replace(/[ \t]+/g, ' ').trim();
}

function normalizeDate(value) {
  const timestamp = Date.parse(value || '');
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Date(timestamp).toISOString().slice(0, 10);
}

function normalizeDomain(value) {
  if (!value) {
    return null;
  }

  try {
    const url = new URL(String(value).includes('://') ? value : `https://${value}`);
    const hostname = url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
    return hostname.includes('.') ? hostname : null;
  } catch {
    return null;
  }
}

function isBlockedDomain(domain) {
  return [...BLOCKED_DOMAINS].some((blocked) => domain === blocked || domain.endsWith(`.${blocked}`));
}
