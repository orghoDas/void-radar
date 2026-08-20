import { Actor, log } from 'apify';

const APOLLO_API_BASE_URL = 'https://api.apollo.io';
const DEFAULT_PERSON_TITLES = [
  'Founder',
  'Co-Founder',
  'CEO',
  'Chief Executive Officer',
  'CTO',
  'Chief Technology Officer',
  'VP Engineering',
  'Vice President Engineering',
  'Head of Engineering',
  'Head of Product',
  'Head of Operations',
];
const DEFAULT_PERSON_SENIORITIES = [
  'founder',
  'owner',
  'c_suite',
  'vp',
  'head',
  'director',
];
const EMAIL_RE = /^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$/;

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const targets = Array.isArray(input.targets) ? input.targets : [];
  const apiKeyEnv = String(input.apiKeyEnv || 'APOLLO_API_KEY');
  if (!isValidEnvVarName(apiKeyEnv)) {
    throw new Error('Invalid apiKeyEnv. Use an environment variable name such as APOLLO_API_KEY, not the API key value.');
  }
  const apiKey = process.env[apiKeyEnv] || input.apolloApiKey || input.apiKey;
  const maxItems = Number(input.maxItems ?? 25);
  const perCompanySearchLimit = Number(input.perCompanySearchLimit ?? 8);
  const maxContactsPerCompany = Number(input.maxContactsPerCompany ?? 2);
  const maxEnrichmentsPerRun = Number(input.maxEnrichmentsPerRun ?? 50);
  const requestDelayMs = Number(input.requestDelayMs ?? 500);
  const personTitles = cleanList(input.personTitles, DEFAULT_PERSON_TITLES);
  const personSeniorities = cleanList(input.personSeniorities, DEFAULT_PERSON_SENIORITIES);
  const revealPersonalEmails = Boolean(input.revealPersonalEmails ?? false);
  const revealPhoneNumber = Boolean(input.revealPhoneNumber ?? false);
  const runWaterfallEmail = Boolean(input.runWaterfallEmail ?? false);
  const emitMissesToDataset = input.emitMissesToDataset !== false;

  if (!apiKey) {
    throw new Error('Missing Apollo API key. Set the encrypted apolloApiKey input field or APOLLO_API_KEY as an Apify secret/environment variable.');
  }
  if (!targets.length) {
    throw new Error('Input must include at least one target.');
  }

  log.info('Starting Apollo verified contact enrichment', {
    targetCount: targets.length,
    maxItems,
    perCompanySearchLimit,
    maxContactsPerCompany,
    maxEnrichmentsPerRun,
    revealPersonalEmails,
    revealPhoneNumber,
    runWaterfallEmail,
  });

  let searchCandidates = 0;
  let enrichmentsAttempted = 0;
  let contactsOutput = 0;
  let missesOutput = 0;
  const misses = [];
  const seenEmails = new Set();

  for (const rawTarget of targets.slice(0, maxItems)) {
    const target = normalizeTarget(rawTarget);
    if (!target.domain) {
      const miss = missRecord(target, 'invalid_domain');
      misses.push(miss);
      missesOutput += 1;
      if (emitMissesToDataset) await Actor.pushData(miss);
      continue;
    }
    if (enrichmentsAttempted >= maxEnrichmentsPerRun) {
      const miss = missRecord(target, 'max_enrichments_per_run_reached');
      misses.push(miss);
      missesOutput += 1;
      if (emitMissesToDataset) await Actor.pushData(miss);
      continue;
    }

    const people = await searchPeople({
      apiKey,
      target,
      personTitles,
      personSeniorities,
      perCompanySearchLimit,
    });
    searchCandidates += people.length;

    if (!people.length) {
      const miss = missRecord(target, 'no_apollo_people_search_results');
      misses.push(miss);
      missesOutput += 1;
      if (emitMissesToDataset) await Actor.pushData(miss);
      await sleep(requestDelayMs);
      continue;
    }

    const enrichmentBudget = Math.max(0, maxEnrichmentsPerRun - enrichmentsAttempted);
    const peopleToEnrich = people.slice(0, Math.min(enrichmentBudget, perCompanySearchLimit));
    enrichmentsAttempted += peopleToEnrich.length;

    const enrichedPeople = await enrichPeople({
      apiKey,
      people: peopleToEnrich,
      revealPersonalEmails,
      revealPhoneNumber,
      runWaterfallEmail,
    });
    const contacts = [];
    for (const person of enrichedPeople) {
      const record = verifiedContactRecord(target, person);
      if (!record) continue;
      const emailKey = record.email.toLowerCase();
      if (seenEmails.has(emailKey)) continue;
      seenEmails.add(emailKey);
      contacts.push(record);
      if (contacts.length >= maxContactsPerCompany) break;
    }

    if (contacts.length) {
      contactsOutput += contacts.length;
      await Actor.pushData(contacts);
    } else {
      const miss = missRecord(target, 'no_verified_email_after_enrichment', {
        apollo_people_found: people.length,
        enrichments_attempted: peopleToEnrich.length,
      });
      misses.push(miss);
      missesOutput += 1;
      if (emitMissesToDataset) await Actor.pushData(miss);
    }

    await Actor.setValue('STATE', {
      lastDomain: target.domain,
      searchCandidates,
      enrichmentsAttempted,
      contactsOutput,
      missesOutput,
    });
    await sleep(requestDelayMs);
  }

  await Actor.setValue('PROVIDER_MISSES', misses);
  log.info('Apollo verified contact enrichment finished', {
    searchCandidates,
    enrichmentsAttempted,
    contactsOutput,
    missesOutput,
  });
});

async function searchPeople({
  apiKey,
  target,
  personTitles,
  personSeniorities,
  perCompanySearchLimit,
}) {
  const url = new URL('/api/v1/mixed_people/api_search', APOLLO_API_BASE_URL);
  url.searchParams.set('per_page', String(perCompanySearchLimit));
  url.searchParams.set('page', '1');
  url.searchParams.set('include_similar_titles', 'false');
  url.searchParams.append('q_organization_domains_list[]', target.domain);
  url.searchParams.append('contact_email_status[]', 'verified');
  for (const title of personTitles) {
    url.searchParams.append('person_titles[]', title);
  }
  for (const seniority of personSeniorities) {
    url.searchParams.append('person_seniorities[]', seniority);
  }

  const payload = await apolloRequest({
    apiKey,
    url,
    body: {},
    operation: 'people_search',
  });
  const people = payload.people || payload.contacts || payload.mixed_people || payload.results || [];
  return people
    .map(normalizeApolloPerson)
    .filter((person) => person.id);
}

async function enrichPeople({
  apiKey,
  people,
  revealPersonalEmails,
  revealPhoneNumber,
  runWaterfallEmail,
}) {
  const enriched = [];
  for (const batch of chunked(people, 10)) {
    const url = new URL('/api/v1/people/bulk_match', APOLLO_API_BASE_URL);
    url.searchParams.set('reveal_personal_emails', String(revealPersonalEmails));
    url.searchParams.set('reveal_phone_number', String(revealPhoneNumber));
    url.searchParams.set('run_waterfall_email', String(runWaterfallEmail));
    const payload = await apolloRequest({
      apiKey,
      url,
      body: {
        details: batch.map((person) => ({ id: person.id })),
      },
      operation: 'people_bulk_match',
    });
    const matches = payload.matches || payload.people || [];
    enriched.push(...matches.map((match) => normalizeApolloPerson(match.person || match)));
  }
  return enriched;
}

async function apolloRequest({ apiKey, url, body, operation }) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'cache-control': 'no-cache',
      'content-type': 'application/json',
      'x-api-key': apiKey,
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
  }
  if (!response.ok) {
    throw new Error(`${operation} failed with HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 500)}`);
  }
  return payload;
}

function verifiedContactRecord(target, person) {
  const email = clean(person.email).toLowerCase();
  const emailStatus = clean(person.email_status || person.emailStatus).toLowerCase();
  if (!EMAIL_RE.test(email) || emailStatus !== 'verified') {
    return null;
  }

  return {
    record_type: 'verified_provider_contact',
    company_id: target.company_id,
    company_domain: target.domain,
    company: target.company,
    target_roles: target.target_roles,
    full_name: person.name || fullName(person),
    role: person.title || '',
    email,
    source_type: 'verified_provider',
    source_url: sourceUrlForPerson(person),
    provider_name: 'apollo',
    verification_status: 'provider_verified',
    confidence: 0.95,
    reason_to_write: target.reason_to_write,
    evidence_urls: target.evidence_urls,
    score: target.score,
    provider_person_id: person.id,
    provider_email_status: emailStatus,
    provider_organization_id: person.organization_id || person.organization?.id || '',
  };
}

function normalizeTarget(rawTarget) {
  return {
    company_id: clean(rawTarget.company_id || rawTarget.companyId),
    company: clean(rawTarget.company),
    domain: normalizeDomain(rawTarget.domain || rawTarget.company_domain || rawTarget.website),
    target_roles: clean(rawTarget.target_roles),
    reason_to_write: clean(rawTarget.reason_to_write),
    evidence_urls: clean(rawTarget.evidence_urls),
    score: rawTarget.score ?? '',
  };
}

function normalizeApolloPerson(value) {
  const person = value || {};
  return {
    ...person,
    id: clean(person.id || person.person_id || person.personId),
    name: clean(person.name),
    first_name: clean(person.first_name || person.firstName),
    last_name: clean(person.last_name || person.lastName),
    title: clean(person.title),
    email: clean(person.email),
    email_status: clean(person.email_status || person.emailStatus),
    linkedin_url: clean(person.linkedin_url || person.linkedinUrl),
  };
}

function sourceUrlForPerson(person) {
  if (person.linkedin_url && person.linkedin_url.startsWith('http')) {
    return person.linkedin_url;
  }
  if (person.id) {
    return `https://app.apollo.io/#/people/${encodeURIComponent(person.id)}`;
  }
  return 'https://app.apollo.io/';
}

function fullName(person) {
  return [person.first_name, person.last_name].filter(Boolean).join(' ').trim();
}

function missRecord(target, reason, extra = {}) {
  return {
    record_type: 'miss',
    provider_name: 'apollo',
    reason,
    company_id: target.company_id,
    company_domain: target.domain,
    company: target.company,
    score: target.score,
    ...extra,
  };
}

function cleanList(value, fallback) {
  if (!Array.isArray(value) || !value.length) return fallback;
  return value.map(clean).filter(Boolean);
}

function normalizeDomain(value) {
  const raw = clean(value).toLowerCase();
  if (!raw) return '';
  try {
    const parsed = new URL(raw.startsWith('http') ? raw : `https://${raw}`);
    return parsed.hostname.replace(/^www\./, '');
  } catch {
    return raw.replace(/^www\./, '').replace(/\/.*$/, '');
  }
}

function chunked(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function clean(value) {
  return String(value ?? '').trim();
}

function isValidEnvVarName(value) {
  return /^[A-Z_][A-Z0-9_]*$/i.test(value);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
