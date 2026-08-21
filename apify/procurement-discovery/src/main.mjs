import { Actor, log } from 'apify';

const OCDS_SEARCH = 'https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search';
const NOTICE_BASE = 'https://www.contractsfinder.service.gov.uk/Notice/';

// Buyers publish through e-sourcing intermediaries, so the contact address is
// often the portal's rather than the organisation's. Those hosts are never the
// prospect and must not become company records.
const PORTAL_DOMAINS = new Set([
  'multiquote.com', 'proactis.com', 'in-tend.co.uk', 'delta-esourcing.com',
  'jaggaer.com', 'bravosolution.com', 'sell2wales.gov.wales', 'publiccontractsscotland.gov.uk',
  'contractsfinder.service.gov.uk', 'gov.uk', 'nhs.net', 'atamis.co.uk',
  'supplierlive.proactisp2p.com', 'mytenders.org', 'due-north.com',
]);

const FREE_MAIL_DOMAINS = new Set([
  'gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.co.uk', 'yahoo.com', 'icloud.com',
]);

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const maxItems = Number(input.maxItems ?? 100);
  const pages = Number(input.pages ?? 5);
  const cpvPrefixes = Array.isArray(input.cpvPrefixes) && input.cpvPrefixes.length
    ? input.cpvPrefixes.map(String)
    : ['72', '48'];
  const requestDelayMs = Number(input.requestDelayMs ?? 600);

  log.info('Starting procurement discovery', { maxItems, pages, cpvPrefixes });

  const records = [];
  const skipped = { no_domain: 0, not_software: 0, portal_only: 0 };
  let cursor = null;

  for (let page = 0; page < pages && records.length < maxItems; page += 1) {
    // Follow the API's own `next` link rather than rebuilding it: the cursor is
    // only valid alongside the publishedTo bound issued with it.
    let url;
    if (cursor) {
      url = new URL(cursor);
    } else {
      url = new URL(OCDS_SEARCH);
      url.searchParams.set('stages', 'tender');
      url.searchParams.set('limit', '100');
    }

    let payload;
    try {
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!response.ok) {
        log.warning('Search request failed', { status: response.status });
        break;
      }
      payload = await response.json();
    } catch (error) {
      log.warning('Search request errored', { error: String(error?.message ?? error) });
      break;
    }

    const releases = payload.releases ?? [];
    if (!releases.length) break;

    for (const release of releases) {
      if (records.length >= maxItems) break;
      const record = standardizeRelease(release, cpvPrefixes, skipped);
      if (record) records.push(record);
    }

    cursor = nextCursor(payload);
    if (!cursor) break;
    await sleep(requestDelayMs);
  }

  if (records.length) await Actor.pushData(records);
  await Actor.setValue('SKIPPED', skipped);
  log.info('Procurement discovery finished', { recordsOutput: records.length, skipped });
});

function standardizeRelease(release, cpvPrefixes, skipped) {
  const tender = release.tender ?? {};
  if (!matchesCpv(tender, cpvPrefixes)) {
    skipped.not_software += 1;
    return null;
  }

  const parties = release.parties ?? [];
  const buyerName = release.buyer?.name ?? parties[0]?.name ?? null;
  const domain = buyerDomain(parties, skipped);
  if (!buyerName || !domain) {
    skipped.no_domain += 1;
    return null;
  }

  const value = tender.value ?? {};
  const deadline = tender.tenderPeriod?.endDate ?? null;
  const sourceUrl = `${NOTICE_BASE}${encodeURIComponent(release.ocid ?? release.id ?? '')}`;

  return {
    source: 'uk_contracts_finder',
    source_record_id: String(release.ocid ?? release.id),
    source_url: sourceUrl,
    company_name: buyerName,
    website: `https://${domain}`,
    domain,
    location: parties[0]?.address?.locality ?? null,
    industry: tender.classification?.description ?? null,
    event_type: 'procurement_notice',
    event_date: (tender.datePublished ?? release.date ?? '').slice(0, 10) || null,
    event_summary: [
      tender.title,
      value.amount ? `Budget ${value.currency ?? ''} ${value.amount}`.trim() : null,
      deadline ? `Deadline ${deadline.slice(0, 10)}` : null,
    ].filter(Boolean).join(' | '),
    description: (tender.description ?? '').slice(0, 2000) || null,
    raw_source_payload: {
      collector: 'procurement-discovery',
      ocid: release.ocid ?? null,
      classification: tender.classification ?? null,
      value,
      tender_period: tender.tenderPeriod ?? null,
      procurement_method: tender.procurementMethodDetails ?? null,
    },
  };
}

function matchesCpv(tender, cpvPrefixes) {
  const codes = [
    tender.classification?.id,
    ...(tender.additionalClassifications ?? []).map((entry) => entry?.id),
  ].filter(Boolean).map(String);
  return codes.some((code) => cpvPrefixes.some((prefix) => code.startsWith(prefix)));
}

function buyerDomain(parties, skipped) {
  // A declared organisation URL is the buyer's own; an email may be the portal's.
  for (const party of parties) {
    const host = hostFromUrl(party?.details?.url);
    if (host && !isPortal(host)) return host;
  }
  for (const party of parties) {
    const email = party?.contactPoint?.email;
    if (!email || !email.includes('@')) continue;
    const host = email.split('@')[1]?.toLowerCase().replace(/^www\./, '');
    if (!host || FREE_MAIL_DOMAINS.has(host)) continue;
    if (isPortal(host)) { skipped.portal_only += 1; continue; }
    return host;
  }
  return null;
}

function isPortal(host) {
  return [...PORTAL_DOMAINS].some((portal) => host === portal || host.endsWith(`.${portal}`));
}

function hostFromUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(String(value).includes('://') ? value : `https://${value}`);
    return url.hostname.toLowerCase().replace(/^www\./, '');
  } catch { return null; }
}

function nextCursor(payload) {
  return payload?.links?.next ?? null;
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
