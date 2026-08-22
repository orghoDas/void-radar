import { Actor, log } from 'apify';

const TED_SEARCH = 'https://api.ted.europa.eu/v3/notices/search';
const NOTICE_BASE = 'https://ted.europa.eu/en/notice/-/detail/';

// TED expert search rejects CPV prefixes, so codes must be given in full.
const DEFAULT_CPV = ['72000000', '72200000', '72300000', '72500000', '48000000', '48800000'];

const FIELDS = [
  'publication-number',
  'notice-title',
  'buyer-name',
  'organisation-internet-address-buyer',
  'organisation-email-buyer',
  'organisation-country-buyer',
  'classification-cpv',
  'deadline-receipt-tender-date-lot',
  'publication-date',
];

const NON_COMPANY_HOSTS = new Set([
  'ted.europa.eu', 'europa.eu', 'ec.europa.eu', 'simap.europa.eu',
  'linkedin.com', 'twitter.com', 'x.com', 'facebook.com', 'youtube.com',
  // National e-procurement portals: the buyer publishes through them, so their
  // host appears as the contact address rather than the organisation's own.
  'marches-publics.gouv.fr', 'boamp.fr', 'contrataciondelestado.es',
  'plataformadecontratacion.es', 'evergabe-online.de', 'dtvp.de',
  'vergabe.nrw.de', 'nen.nl', 'tenderned.nl', 'mercell.com', 'eu-supply.com',
  'ted.europa.eu', 'ezamowienia.gov.pl', 'platformazakupowa.pl',
  'nen.gov.pt', 'acingov.pt', 'etendering.ted.europa.eu', 'e-licitatie.ro',
]);

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const maxItems = Number(input.maxItems ?? 250);
  const daysBack = Number(input.daysBack ?? 30);
  const cpvCodes = Array.isArray(input.cpvCodes) && input.cpvCodes.length
    ? input.cpvCodes.map(String) : DEFAULT_CPV;
  const countries = Array.isArray(input.countries) ? input.countries.map(String) : [];
  const requestDelayMs = Number(input.requestDelayMs ?? 600);

  let query = `classification-cpv IN (${cpvCodes.join(' ')}) AND publication-date >= today(-${daysBack})`;
  if (countries.length) {
    query += ` AND organisation-country-buyer IN (${countries.join(' ')})`;
  }

  log.info('Starting TED discovery', { maxItems, daysBack, cpvCodes, countries });

  const records = [];
  const skipped = { no_domain: 0, no_name: 0, duplicate: 0 };
  const seen = new Set();
  const pageSize = 100;

  for (let page = 1; records.length < maxItems; page += 1) {
    let payload;
    try {
      const response = await fetch(TED_SEARCH, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ query, limit: pageSize, page, fields: FIELDS }),
      });
      if (!response.ok) {
        log.warning('TED search failed', { status: response.status, page });
        break;
      }
      payload = await response.json();
    } catch (error) {
      log.warning('TED request errored', { error: String(error?.message ?? error) });
      break;
    }

    const notices = payload.notices ?? [];
    if (!notices.length) break;

    for (const notice of notices) {
      if (records.length >= maxItems) break;
      const record = standardizeNotice(notice, skipped, seen);
      if (record) records.push(record);
    }

    if (notices.length < pageSize) break;
    await sleep(requestDelayMs);
  }

  if (records.length) await Actor.pushData(records);
  await Actor.setValue('SKIPPED', skipped);
  log.info('TED discovery finished', { recordsOutput: records.length, skipped });
});

function standardizeNotice(notice, skipped, seen) {
  const name = firstMultilingual(notice['buyer-name']);
  if (!name) { skipped.no_name += 1; return null; }

  const domain = firstDomain(notice['organisation-internet-address-buyer'])
    ?? domainFromEmail(notice['organisation-email-buyer']);
  if (!domain) { skipped.no_domain += 1; return null; }

  const publication = String(firstValue(notice['publication-number']) ?? '');
  const key = `${domain}:${publication}`;
  if (seen.has(key)) { skipped.duplicate += 1; return null; }
  seen.add(key);

  const deadline = String(firstValue(notice['deadline-receipt-tender-date-lot']) ?? '').slice(0, 10);
  const title = firstMultilingual(notice['notice-title']) ?? 'EU tender notice';
  const country = firstValue(notice['organisation-country-buyer']);

  return {
    source: 'eu_ted',
    source_record_id: `ted:${publication}`,
    source_url: `${NOTICE_BASE}${encodeURIComponent(publication)}`,
    company_name: name,
    website: `https://${domain}`,
    domain,
    location: country ? String(country) : null,
    industry: null,
    event_type: 'procurement_notice',
    event_date: String(firstValue(notice['publication-date']) ?? '').slice(0, 10) || null,
    event_summary: [title, deadline ? `Deadline ${deadline}` : null].filter(Boolean).join(' | '),
    description: title.slice(0, 2000),
    contact_email: normalizeEmail(firstValue(notice['organisation-email-buyer'])),
    raw_source_payload: {
      collector: 'ted-discovery',
      publication_number: publication,
      country,
      cpv: notice['classification-cpv'] ?? null,
      tender_period: deadline ? { endDate: deadline } : null,
    },
  };
}

// TED returns names as {lang: [value]} maps; prefer English where published.
function firstMultilingual(value) {
  if (typeof value === 'string') return value.trim() || null;
  if (Array.isArray(value)) return firstMultilingual(value[0]);
  if (value && typeof value === 'object') {
    for (const lang of ['eng', 'ENG', 'en']) {
      if (value[lang]) return firstMultilingual(value[lang]);
    }
    return firstMultilingual(Object.values(value)[0]);
  }
  return null;
}

function firstValue(value) {
  if (Array.isArray(value)) return value[0];
  if (value && typeof value === 'object') return Object.values(value)[0];
  return value;
}

function firstDomain(value) {
  const candidates = Array.isArray(value) ? value : [value];
  for (const candidate of candidates) {
    const host = hostFromUrl(candidate);
    if (host && !isBlocked(host)) return host;
  }
  return null;
}

function domainFromEmail(value) {
  const email = normalizeEmail(firstValue(value));
  if (!email) return null;
  const host = email.split('@')[1];
  return host && !isBlocked(host) ? host : null;
}

function normalizeEmail(value) {
  if (typeof value !== 'string') return null;
  const email = value.trim().toLowerCase();
  return /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(email) ? email : null;
}

function isBlocked(host) {
  return [...NON_COMPANY_HOSTS].some((blocked) => host === blocked || host.endsWith(`.${blocked}`));
}

function hostFromUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value.includes('://') ? value : `https://${value}`);
    return url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
  } catch { return null; }
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
