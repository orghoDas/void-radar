import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';
import { readFile } from 'node:fs/promises';

const DEFAULT_FEEDS = [
  {
    source: 'funding_news',
    sourceName: 'Funding News',
    url: 'https://www.uktech.news/feed',
    eventType: 'funding',
  },
];

const BLOCKED_DOMAINS = new Set([
  'facebook.com',
  'linkedin.com',
  'twitter.com',
  'x.com',
  'youtube.com',
  'instagram.com',
  'medium.com',
  'substack.com',
  // Article pages embed analytics, CDN and consent scripts. Their hosts appear
  // before the company's own link and get captured as the company domain.
  'googletagmanager.com',
  'google-analytics.com',
  'googleapis.com',
  'gstatic.com',
  'doubleclick.net',
  'cloudflare.com',
  'cloudfront.net',
  'cookiebot.com',
  'onetrust.com',
  'hotjar.com',
  'segment.com',
  'sentry.io',
  'gravatar.com',
  'wp.com',
  'w3.org',
  'schema.org',
  'archive.org',
  'bit.ly',
]);

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const maxItems = Number(input.maxItems ?? 50);
  const feeds = Array.isArray(input.feeds) && input.feeds.length ? input.feeds : DEFAULT_FEEDS;
  const includeArticleFetch = Boolean(input.includeArticleFetch ?? false);
  const requestDelayMs = Number(input.requestDelayMs ?? 500);
  const records = [];

  log.info('Starting funding/news discovery', {
    maxItems,
    feedCount: feeds.length,
    includeArticleFetch,
    requestDelayMs,
  });

  for (const feed of feeds) {
    if (records.length >= maxItems) {
      break;
    }

    const feedUrl = String(feed.url ?? '').trim();
    if (!feedUrl) {
      log.warning('Skipping feed without URL', { feed });
      continue;
    }

    const xml = await fetchText(feedUrl);
    const items = parseFeedItems(xml, feedUrl);

    for (const [index, item] of items.entries()) {
      if (records.length >= maxItems) {
        break;
      }

      const record = await standardizeItem(item, feed, {
        includeArticleFetch,
        requestDelayMs,
      });
      if (!record) {
        continue;
      }

      records.push({
        ...record,
        discovery_metadata: {
          collector: 'funding-news-discovery',
          feed_url: feedUrl,
          feed_item_offset: index,
        },
      });

      await Actor.setValue('STATE', {
        feedUrl,
        lastFeedItemOffset: index,
        recordsOutput: records.length,
      });
    }
  }

  await Actor.pushData(records);
  log.info('Funding/news discovery finished', { recordsOutput: records.length });
});

async function standardizeItem(item, feed, options) {
  const sourceUrl = item.link || item.guid;
  const title = cleanText(item.title);
  const summary = cleanText(item.description || item.content || title);
  if (!sourceUrl || !title) {
    return null;
  }

  const blockedDomains = new Set(
    [normalizeDomain(feed.url), normalizeDomain(sourceUrl)].filter(Boolean)
  );
  let candidateUrl = extractFirstCompanyUrl(item, blockedDomains);
  let articleText = '';
  if (!candidateUrl && options.includeArticleFetch) {
    await sleep(options.requestDelayMs);
    articleText = await fetchArticleText(sourceUrl);
    candidateUrl = extractUrlFromText(articleText, blockedDomains);
  }

  const domain = normalizeDomain(candidateUrl);
  const companyName = inferCompanyName(title, summary, domain);
  if (!domain || !companyName) {
    return null;
  }

  const eventDate = normalizeDate(item.pubDate || item.updated || item.published);
  return {
    source: String(feed.source ?? 'funding_news'),
    source_url: sourceUrl,
    source_record_id: item.guid || sourceUrl,
    company_name: companyName,
    website: `https://${domain}`,
    domain,
    location: feed.location ?? null,
    industry: feed.industry ?? null,
    stage: null,
    status: 'active',
    employee_count: null,
    description: summary || title,
    tags: ['funding'],
    event_type: feed.eventType ?? 'funding',
    event_date: eventDate,
    event_summary: title,
    raw_source_payload: {
      ...item,
      article_text_sample: articleText ? articleText.slice(0, 1000) : undefined,
      source_name: feed.sourceName,
    },
  };
}

function parseFeedItems(xml, feedUrl) {
  const $ = cheerio.load(xml, { xmlMode: true });
  const rssItems = $('item')
    .toArray()
    .map((element) => ({
      title: text($, element, 'title'),
      link: text($, element, 'link'),
      guid: text($, element, 'guid'),
      pubDate: text($, element, 'pubDate'),
      description: text($, element, 'description'),
      content: text($, element, 'content\\:encoded'),
    }));

  if (rssItems.length) {
    return rssItems;
  }

  return $('entry')
    .toArray()
    .map((element) => {
      const entry = $(element);
      const link =
        entry.find('link[rel="alternate"]').attr('href') ||
        entry.find('link').first().attr('href') ||
        '';
      return {
        title: text($, element, 'title'),
        link: normalizeAbsoluteUrl(link, feedUrl),
        guid: text($, element, 'id'),
        pubDate: text($, element, 'published'),
        updated: text($, element, 'updated'),
        description: text($, element, 'summary'),
        content: text($, element, 'content'),
      };
    });
}

function text($, element, selector) {
  return cleanText($(element).find(selector).first().text());
}

function extractFirstCompanyUrl(item, blockedDomains) {
  const rawText = [item.description, item.content].filter(Boolean).join(' ');
  return extractUrlFromText(rawText, blockedDomains);
}

function extractUrlFromText(value, blockedDomains = new Set()) {
  const $ = cheerio.load(value || '');
  const href = $('a[href]')
    .toArray()
    .map((element) => $(element).attr('href'))
    .find((candidate) => {
      const domain = normalizeDomain(candidate);
      return domain && !isBlockedDomain(domain, blockedDomains);
    });
  if (href) {
    return href;
  }

  const match = String(value || '').match(/https?:\/\/[^\s"'<>]+/i);
  if (!match) {
    return null;
  }

  const matchedDomain = normalizeDomain(match[0]);
  if (!matchedDomain || isBlockedDomain(matchedDomain, blockedDomains)) {
    return null;
  }
  return match[0];
}

function inferCompanyName(title, summary, domain) {
  const value = cleanText(title || summary);
  const raiseMatch = value.match(/^(.+?)\s+(raises|raised|secures|secured|lands|landed|closes|closed)\b/i);
  if (raiseMatch) {
    return cleanCompanyName(raiseMatch[1]);
  }

  const fundingMatch = value.match(/^(.+?)\s+(gets|receives|bags|announces)\b/i);
  if (fundingMatch) {
    return cleanCompanyName(fundingMatch[1]);
  }

  if (domain) {
    const base = domain.split('.')[0].replace(/[-_]+/g, ' ');
    return cleanCompanyName(base.replace(/\b\w/g, (letter) => letter.toUpperCase()));
  }

  return null;
}

function cleanCompanyName(value) {
  return cleanText(value)
    .replace(/^startup\s+/i, '')
    .replace(/\s+startup$/i, '')
    .replace(/[,:;\-.]+$/g, '')
    .trim();
}

async function fetchArticleText(url) {
  try {
    const html = await fetchText(url);
    const $ = cheerio.load(html);
    $('script, style, nav, footer, header').remove();
    return cleanText($('body').text());
  } catch (error) {
    log.warning('Article fetch failed', {
      url,
      error: error instanceof Error ? error.message : String(error),
    });
    return '';
  }
}

async function fetchText(url) {
  if (String(url).startsWith('file://')) {
    return readFile(new URL(url), 'utf8');
  }

  const response = await fetch(url, {
    headers: {
      accept: 'application/rss+xml,application/atom+xml,text/xml,text/html',
      'user-agent': 'VoidRadarFundingNewsDiscovery/0.1 (+mailto:hello@voidstudio.tech)',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }

  return response.text();
}

function normalizeDate(value) {
  const timestamp = Date.parse(value || '');
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Date(timestamp).toISOString().slice(0, 10);
}

function normalizeAbsoluteUrl(value, baseUrl) {
  if (!value) {
    return '';
  }
  try {
    return new URL(value, baseUrl).toString();
  } catch {
    return '';
  }
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

function isBlockedDomain(domain, blockedDomains = new Set()) {
  const allBlockedDomains = new Set([...BLOCKED_DOMAINS, ...blockedDomains]);
  return [...allBlockedDomains].some((blocked) => domain === blocked || domain.endsWith(`.${blocked}`));
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
