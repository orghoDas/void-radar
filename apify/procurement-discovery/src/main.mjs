import { Actor, log } from 'apify';

// Both UK portals publish OCDS, but they differ in endpoint, query params and
// - critically - where CPV codes live. Find a Tender leaves
// tender.classification empty on ~76% of releases and puts the code under
// tender.items[].additionalClassifications, so reading only the Contracts
// Finder path returns zero records silently.
const PORTALS = {
  contracts_finder: {
    source: 'uk_contracts_finder',
    sourceName: 'UK Contracts Finder',
    searchUrl: 'https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search',
    params: { stages: 'tender', limit: '100' },
    noticeBase: 'https://www.contractsfinder.service.gov.uk/Notice/',
  },
  find_a_tender: {
    source: 'uk_find_a_tender',
    sourceName: 'UK Find a Tender',
    searchUrl: 'https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages',
    params: { limit: '100' },
    noticeBase: 'https://www.find-tender.service.gov.uk/notice/',
  },
};

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
  const portalKey = String(input.portal ?? 'contracts_finder');
  const portal = PORTALS[portalKey];
  if (!portal) {
    throw new Error(`Unknown portal "${portalKey}". Known: ${Object.keys(PORTALS).join(', ')}`);
  }

  log.info('Starting procurement discovery', {
    portal: portalKey, maxItems, pages, cpvPrefixes,
  });

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
      url = new URL(portal.searchUrl);
      for (const [key, value] of Object.entries(portal.params)) {
        url.searchParams.set(key, value);
      }
    }

    let payload;
    try {
      const response = await fetchWithTimeout(url, {
        headers: { Accept: 'application/json' },
        timeoutMs: Number(input.requestTimeoutMs ?? 30000),
      });
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
      const record = standardizeRelease(release, cpvPrefixes, skipped, portal);
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

function standardizeRelease(release, cpvPrefixes, skipped, portal) {
  const tender = release.tender ?? {};
  const cpvCodes = collectCpvCodes(tender);
  const matchedCpvCodes = cpvCodes.filter((code) => (
    cpvPrefixes.some((prefix) => code.startsWith(prefix))
  ));
  if (!matchedCpvCodes.length) {
    skipped.not_software += 1;
    return null;
  }

  const parties = release.parties ?? [];
  const buyerName = release.buyer?.name ?? parties[0]?.name ?? null;
  const domain = buyerDomain(parties, skipped);
  // The notice names who to contact about this specific tender. That is public
  // record and the strongest contact provenance available, so keep it.
  const contact = buyerContact(parties, domain);
  if (!buyerName || !domain) {
    skipped.no_domain += 1;
    return null;
  }

  const value = tender.value ?? {};
  const deadline = tender.tenderPeriod?.endDate ?? null;
  const sourceUrl = `${portal.noticeBase}${encodeURIComponent(release.ocid ?? release.id ?? '')}`;

  return {
    source: portal.source,
    source_record_id: String(release.ocid ?? release.id),
    source_url: sourceUrl,
    company_name: buyerName,
    website: `https://${domain}`,
    domain,
    location: parties[0]?.address?.locality ?? null,
    industry: classificationDescription(tender, matchedCpvCodes)
      ?? tender.classification?.description
      ?? tender.items?.[0]?.additionalClassifications?.[0]?.description
      ?? null,
    organisation_type: organisationType(parties),
    event_type: 'procurement_notice',
    event_date: (tender.datePublished ?? release.date ?? '').slice(0, 10) || null,
    event_summary: [
      tender.title,
      value.amount ? `Budget ${value.currency ?? ''} ${value.amount}`.trim() : null,
      deadline ? `Deadline ${deadline.slice(0, 10)}` : null,
    ].filter(Boolean).join(' | '),
    description: (tender.description ?? '').slice(0, 2000) || null,
    contact_name: contact.name,
    contact_email: contact.email,
    contact_phone: contact.phone,
    contact_is_portal: contact.isPortal,
    raw_source_payload: {
      collector: 'procurement-discovery',
      ocid: release.ocid ?? null,
      classification: tender.classification ?? null,
      cpv_codes: cpvCodes,
      matched_cpv_codes: matchedCpvCodes,
      value,
      tender_period: tender.tenderPeriod ?? null,
      procurement_method: tender.procurementMethodDetails ?? null,
    },
  };
}

function collectCpvCodes(tender) {
  const codes = [
    tender.classification?.id,
    ...(tender.additionalClassifications ?? []).map((entry) => entry?.id),
  ];
  for (const item of tender.items ?? []) {
    codes.push(item?.classification?.id);
    for (const extra of item?.additionalClassifications ?? []) {
      codes.push(extra?.id);
    }
  }
  return codes.filter(Boolean).map(String);
}

async function fetchWithTimeout(url, { timeoutMs, ...options }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

function classificationDescription(tender, matchedCpvCodes) {
  const descriptions = [
    tender.classification,
    ...(tender.additionalClassifications ?? []),
  ];
  for (const item of tender.items ?? []) {
    descriptions.push(item?.classification);
    descriptions.push(...(item?.additionalClassifications ?? []));
  }
  for (const entry of descriptions) {
    if (entry?.id && matchedCpvCodes.includes(String(entry.id)) && entry.description) {
      return entry.description;
    }
  }
  return null;
}

// Find a Tender states what kind of organisation the buyer is. That is better
// evidence of "non-technical buyer" than guessing from the name.
function organisationType(parties) {
  for (const party of parties ?? []) {
    for (const entry of party?.details?.classifications ?? []) {
      if (entry?.scheme === 'UK_CA_TYPE' && entry?.description) {
        return String(entry.description);
      }
    }
  }
  return null;
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

function buyerContact(parties, domain) {
  let fallback = { name: null, email: null, phone: null, isPortal: false };
  for (const party of parties) {
    const point = party?.contactPoint;
    if (!point?.email) continue;
    const host = String(point.email).split('@')[1]?.toLowerCase();
    const entry = {
      name: point.name ?? null,
      email: String(point.email).toLowerCase(),
      phone: point.telephone ?? null,
      isPortal: isPortal(host ?? ''),
    };
    // An address on the buyer's own domain is the one worth having.
    if (host && domain && host.replace(/^www\./, '') === domain) return entry;
    if (!entry.isPortal && !fallback.email) fallback = entry;
  }
  return fallback;
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
