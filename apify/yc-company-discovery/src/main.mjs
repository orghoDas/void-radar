import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';

const YC_SOURCE = 'y_combinator';
const DEFAULT_SOURCE_URL = 'https://yc-oss.github.io/api/companies/all.json';
const DEFAULT_REGIONS = [
  'United States',
  'United States of America',
  'USA',
  'US',
  'United Kingdom',
  'UK',
  'England',
  'Ireland',
  'Germany',
  'France',
  'Netherlands',
  'Spain',
  'Italy',
  'Sweden',
  'Norway',
  'Denmark',
  'Finland',
  'Poland',
  'Portugal',
  'Belgium',
  'Switzerland',
  'Austria',
  'Europe',
];

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const maxItems = Number(input.maxItems ?? 50);
  const minEmployees = Number(input.minEmployees ?? 50);
  const sourceUrl = input.sourceUrl ?? DEFAULT_SOURCE_URL;
  const startOffset = Number(input.startOffset ?? 0);
  const includeUnknownLocation = Boolean(input.includeUnknownLocation ?? false);
  const includeFounderDetails = input.includeFounderDetails !== false;
  const detailRequestDelayMs = Number(input.detailRequestDelayMs ?? 300);
  const regions = Array.isArray(input.regions) ? input.regions : DEFAULT_REGIONS;

  log.info('Starting YC company discovery', {
    maxItems,
    minEmployees,
    sourceUrl,
    startOffset,
    includeUnknownLocation,
    includeFounderDetails,
    detailRequestDelayMs,
    regions,
  });

  const rawCompanies = await fetchCompanies(sourceUrl);
  const records = [];

  for (let index = startOffset; index < rawCompanies.length; index += 1) {
    const raw = rawCompanies[index];
    const record = standardizeCompany(raw);

    if (!record.source_company_id || !record.company_name || !record.source_url) {
      continue;
    }

    if (!passesEmployeeFilter(record, minEmployees)) {
      continue;
    }

    if (!passesRegionFilter(record, regions, includeUnknownLocation)) {
      continue;
    }

    if (includeFounderDetails) {
      record.founders = await fetchFounderDetails(record.source_url);
      await sleep(detailRequestDelayMs);
    }

    records.push({
      ...record,
      discovery_metadata: {
        collector: 'yc-company-discovery',
        source_url: sourceUrl,
        source_offset: index,
      },
      raw_source_payload: raw,
    });

    await Actor.setValue('STATE', {
      sourceUrl,
      lastSourceOffset: index,
      recordsOutput: records.length,
    });

    if (records.length >= maxItems) {
      break;
    }
  }

  await Actor.pushData(records);

  log.info('YC company discovery finished', {
    recordsOutput: records.length,
    sourceRecordsScanned: rawCompanies.length,
  });
});

async function fetchCompanies(sourceUrl) {
  const response = await fetch(sourceUrl, {
    headers: {
      accept: 'application/json',
      'user-agent': 'VoidRadarYCDiscovery/0.1',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch YC company feed: ${response.status}`);
  }

  const body = await response.json();

  if (Array.isArray(body)) {
    return body;
  }

  if (Array.isArray(body.companies)) {
    return body.companies;
  }

  if (Array.isArray(body.results)) {
    return body.results;
  }

  throw new Error('YC company feed did not contain a company array.');
}

async function fetchFounderDetails(sourceUrl) {
  if (!sourceUrl) {
    return [];
  }

  try {
    const response = await fetch(sourceUrl, {
      headers: {
        accept: 'text/html,application/xhtml+xml',
        'user-agent': 'VoidRadarYCDiscovery/0.1',
      },
    });

    if (!response.ok) {
      log.warning('Failed to fetch YC company profile for founder details', {
        sourceUrl,
        status: response.status,
      });
      return [];
    }

    const html = await response.text();
    return extractFoundersFromHtml(html, sourceUrl);
  } catch (error) {
    log.warning('Founder detail fetch failed', {
      sourceUrl,
      error: error instanceof Error ? error.message : String(error),
    });
    return [];
  }
}

function extractFoundersFromHtml(html, sourceUrl) {
  const $ = cheerio.load(html);
  const fromInertia = extractFoundersFromInertiaPage($, sourceUrl);
  if (fromInertia.length) {
    return dedupeFounders(fromInertia);
  }

  return dedupeFounders(extractFoundersFromFounderLinks($, sourceUrl));
}

function extractFoundersFromInertiaPage($, sourceUrl) {
  const rawPage = $('[data-page]').attr('data-page');
  if (!rawPage) {
    return [];
  }

  try {
    const page = JSON.parse(rawPage);
    return findFounderArrays(page).flatMap((founders) =>
      founders.map((founder) => normalizeFounderObject(founder, sourceUrl)).filter(Boolean)
    );
  } catch (error) {
    log.debug('Unable to parse YC Inertia page payload for founders', {
      sourceUrl,
      error: error instanceof Error ? error.message : String(error),
    });
    return [];
  }
}

function findFounderArrays(value, path = []) {
  if (!value || typeof value !== 'object') {
    return [];
  }

  if (Array.isArray(value)) {
    const keyPath = path.join('.').toLowerCase();
    if (keyPath.includes('founder')) {
      return [value];
    }

    return value.flatMap((item, index) => findFounderArrays(item, [...path, String(index)]));
  }

  return Object.entries(value).flatMap(([key, child]) =>
    findFounderArrays(child, [...path, key])
  );
}

function normalizeFounderObject(founder, sourceUrl) {
  if (!founder || typeof founder !== 'object') {
    return null;
  }

  const name = firstPresent(
    founder.name,
    founder.full_name,
    founder.fullName,
    founder.title,
    founder.username
  );

  if (!name) {
    return null;
  }

  const profileUrl = normalizeProfileUrl(
    firstPresent(founder.url, founder.profile_url, founder.profileUrl, founder.path),
    sourceUrl
  );
  const linkedinUrl = firstPresent(
    founder.linkedin_url,
    founder.linkedinUrl,
    founder.linkedin,
    founder.linkedin_link
  );
  const xUrl = firstPresent(founder.twitter_url, founder.twitterUrl, founder.twitter, founder.x_url);

  return {
    name: String(name),
    role: firstPresent(founder.role, founder.title, founder.title_text, founder.position),
    profile_url: profileUrl,
    linkedin_url: normalizeAbsoluteUrl(linkedinUrl, sourceUrl),
    x_url: normalizeAbsoluteUrl(
      firstPresent(xUrl, founder.twitter_url, founder.twitterUrl),
      sourceUrl
    ),
    bio: firstPresent(founder.bio, founder.founder_bio, founder.description, founder.about),
    email: extractFirstEmail(JSON.stringify(founder)),
  };
}

function extractFoundersFromFounderLinks($, sourceUrl) {
  const founders = [];

  $('a[href*="/people/"], a[href*="linkedin.com/in/"]').each((_index, element) => {
    const link = $(element);
    const href = link.attr('href');
    const card = link.closest('div, li, article, section');
    const cardText = card.text().replace(/\s+/g, ' ').trim();
    const linkText = link.text().replace(/\s+/g, ' ').trim();
    const imgAlt = link.find('img[alt]').attr('alt');
    const name = firstPresent(linkText, imgAlt, inferNameFromCardText(cardText));

    if (!name) {
      return;
    }

    founders.push({
      name,
      role: inferRole(cardText),
      profile_url: href && href.includes('/people/') ? normalizeAbsoluteUrl(href, sourceUrl) : null,
      linkedin_url: href && href.includes('linkedin.com') ? normalizeAbsoluteUrl(href, sourceUrl) : null,
      x_url: extractSocialUrl($, card, sourceUrl, ['twitter.com', 'x.com']),
      bio: cardText || null,
      email: extractFirstEmail(cardText),
    });
  });

  return founders;
}

function normalizeProfileUrl(value, sourceUrl) {
  return normalizeAbsoluteUrl(value, sourceUrl);
}

function normalizeAbsoluteUrl(value, sourceUrl) {
  if (!value || typeof value !== 'string') {
    return null;
  }

  try {
    return new URL(value, sourceUrl).toString();
  } catch {
    return null;
  }
}

function inferNameFromCardText(value) {
  if (!value) {
    return null;
  }

  const candidate = value.split(/Founder|CEO|CTO|COO|Chief|LinkedIn|Twitter|X/i)[0]?.trim();
  return candidate && candidate.length <= 80 ? candidate : null;
}

function inferRole(value) {
  if (!value) {
    return null;
  }

  const match = value.match(
    /\b(Co-Founder|Cofounder|Founder\/CEO|Founder|CEO|CTO|COO|Chief [A-Za-z ]+ Officer)\b/i
  );

  return match ? match[0] : null;
}

function extractSocialUrl($, card, sourceUrl, domains) {
  const link = card
    .find('a[href]')
    .toArray()
    .map((element) => $(element).attr('href'))
    .find((href) => domains.some((domain) => href?.includes(domain)));

  return normalizeAbsoluteUrl(link, sourceUrl);
}

function extractFirstEmail(value) {
  if (!value) {
    return null;
  }

  const match = String(value).match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return match ? match[0] : null;
}

function dedupeFounders(founders) {
  const seen = new Set();
  const deduped = [];

  for (const founder of founders) {
    const key = String(firstPresent(founder.name, founder.linkedin_url, founder.profile_url))
      .toLowerCase()
      .trim();
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(founder);
  }

  return deduped;
}

function standardizeCompany(raw) {
  const slug = firstPresent(raw.slug, raw.company_slug, raw.url_slug, raw.id, raw.objectID);
  const ycUrl = normalizeYcUrl(firstPresent(raw.yc_url, raw.url, raw.source_url), slug);
  const website = firstPresent(raw.website, raw.website_url, raw.domain, raw.company_url);
  const founders = normalizeFounders(firstPresent(raw.founders, raw.founder_names, []));
  const tags = normalizeStringList(firstPresent(raw.tags, raw.regions, raw.industries, []));

  return {
    source: YC_SOURCE,
    source_url: ycUrl,
    source_company_id: String(firstPresent(raw.id, raw.objectID, slug, raw.name) ?? ''),
    company_name: String(firstPresent(raw.name, raw.company_name, raw.title) ?? ''),
    website: normalizeWebsite(website),
    location: normalizeLocation(raw),
    industry: firstPresent(raw.industry, raw.primary_industry, raw.vertical, tags[0]),
    batch: firstPresent(raw.batch, raw.yc_batch),
    stage: firstPresent(raw.stage, raw.status),
    status: firstPresent(raw.status, raw.company_status),
    employee_count: normalizeEmployeeCount(
      firstPresent(raw.team_size, raw.employee_count, raw.employees)
    ),
    description: firstPresent(raw.one_liner, raw.description, raw.long_description),
    tags,
    founders,
  };
}

function normalizeYcUrl(value, slug) {
  if (typeof value === 'string' && value.startsWith('https://www.ycombinator.com/')) {
    return value;
  }

  if (typeof value === 'string' && value.startsWith('/companies/')) {
    return `https://www.ycombinator.com${value}`;
  }

  if (slug) {
    return `https://www.ycombinator.com/companies/${slug}`;
  }

  return null;
}

function normalizeWebsite(value) {
  if (!value || typeof value !== 'string') {
    return null;
  }

  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value;
  }

  return `https://${value}`;
}

function normalizeLocation(raw) {
  const value = firstPresent(raw.location, raw.headquarters, raw.region, raw.country);
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(', ');
  }

  if (typeof value === 'string') {
    return value;
  }

  if (Array.isArray(raw.all_locations)) {
    return raw.all_locations.filter(Boolean).join(', ');
  }

  if (typeof raw.all_locations === 'string') {
    return raw.all_locations;
  }

  return null;
}

function normalizeEmployeeCount(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeFounders(value) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((founder) => {
      if (typeof founder === 'string') {
        return { name: founder };
      }

      const name = firstPresent(founder.name, founder.full_name, founder.title);
      if (!name) {
        return null;
      }

      return {
        name: String(name),
        role: firstPresent(founder.role, founder.title_text),
      };
    })
    .filter(Boolean);
}

function normalizeStringList(value) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((item) => {
      if (typeof item === 'string') {
        return item;
      }
      return firstPresent(item.name, item.title, item.slug);
    })
    .filter(Boolean)
    .map(String);
}

function passesEmployeeFilter(record, minEmployees) {
  if (!minEmployees || minEmployees <= 0) {
    return true;
  }

  return typeof record.employee_count === 'number' && record.employee_count >= minEmployees;
}

function passesRegionFilter(record, regions, includeUnknownLocation) {
  if (!regions.length) {
    return true;
  }

  if (!record.location) {
    return includeUnknownLocation;
  }

  const location = record.location.toLowerCase();
  return regions.some((region) => location.includes(String(region).toLowerCase()));
}

function firstPresent(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== '');
}

function sleep(ms) {
  if (!ms || ms <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve) => setTimeout(resolve, ms));
}
