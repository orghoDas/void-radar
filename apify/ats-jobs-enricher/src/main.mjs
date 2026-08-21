import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';

const DEFAULT_BOARDS = [
  {
    company_id: null,
    domain: 'snout.com',
    ats_provider: 'generic',
    board_token: 'jobs.gem.com/snout',
    board_url: 'https://jobs.gem.com/snout',
    careers_url: 'https://jobs.gem.com/snout',
  },
  {
    company_id: null,
    domain: 'marpledata.com',
    ats_provider: 'generic',
    board_token: 'app.notion.com/p/getmarple/careers-marple-3c2fa12cc1cf80baabe9d647aaeaf17b',
    board_url: 'https://app.notion.com/p/getmarple/Careers-Marple-3c2fa12cc1cf80baabe9d647aaeaf17b?source=copy_link',
    careers_url: 'https://app.notion.com/p/getmarple/Careers-Marple-3c2fa12cc1cf80baabe9d647aaeaf17b?source=copy_link',
  },
];

const STACK_TERMS = [
  'aws',
  'azure',
  'django',
  'docker',
  'fastapi',
  'go',
  'graphql',
  'java',
  'javascript',
  'kubernetes',
  'llm',
  'node',
  'node.js',
  'postgres',
  'postgresql',
  'python',
  'rails',
  'react',
  'ruby',
  'tailwind',
  'typescript',
];

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const boards = Array.isArray(input.boards) && input.boards.length ? input.boards : DEFAULT_BOARDS;
  const maxBoards = Number(input.maxBoards ?? 100);
  const maxJobsPerBoard = Number(input.maxJobsPerBoard ?? 100);
  const requestDelayMs = Number(input.requestDelayMs ?? 250);
  const requestTimeoutMs = Number(input.requestTimeoutMs ?? 8000);
  const includeGenericHtml = input.includeGenericHtml !== false;

  log.info('Starting ATS jobs enrichment', {
    boardCount: boards.length,
    maxBoards,
    maxJobsPerBoard,
    includeGenericHtml,
  });

  const failedBoards = [];
  let jobsOutput = 0;

  for (const board of boards.slice(0, maxBoards)) {
    // A board can 404 or time out (a stale Lever slug, a careers page that moved).
    // That is per-board evidence, not a reason to abandon the remaining batch.
    let jobs = [];
    try {
      jobs = await fetchJobsForBoard(board, { includeGenericHtml, requestTimeoutMs });
    } catch (error) {
      log.warning('Board fetch failed', {
        domain: board.domain ?? null,
        board_url: board.board_url ?? null,
        error: String(error?.message ?? error),
      });
      failedBoards.push({
        domain: board.domain ?? null,
        ats_provider: board.ats_provider ?? null,
        board_url: board.board_url ?? null,
        reason: 'fetch_failed',
        error: String(error?.message ?? error),
      });
      await sleep(requestDelayMs);
      continue;
    }

    if (!jobs.length) {
      failedBoards.push({
        domain: board.domain ?? null,
        ats_provider: board.ats_provider ?? null,
        board_url: board.board_url ?? null,
        reason: 'no_jobs_found',
      });
    }

    const limitedJobs = jobs.slice(0, maxJobsPerBoard);
    if (limitedJobs.length) {
      await Actor.pushData(limitedJobs);
      jobsOutput += limitedJobs.length;
    }

    await Actor.setValue('STATE', {
      lastBoardUrl: board.board_url ?? null,
      jobsOutput,
      failedBoards: failedBoards.length,
    });
    await sleep(requestDelayMs);
  }

  await Actor.setValue('JOB_BOARD_FAILURES', failedBoards);
  log.info('ATS jobs enrichment finished', {
    jobsOutput,
    failedBoards: failedBoards.length,
  });
});

async function fetchJobsForBoard(board, options) {
  const provider = normalizeProvider(board.ats_provider);
  try {
    if (provider === 'greenhouse') {
      return fetchGreenhouseJobs(board, options);
    }
    if (provider === 'lever') {
      return fetchLeverJobs(board, options);
    }
    if (provider === 'ashby') {
      return fetchAshbyJobs(board, options);
    }
    if (provider === 'workable') {
      return fetchGenericHtmlJobs(board, 'workable', options);
    }
    if (options.includeGenericHtml) {
      return fetchGenericHtmlJobs(board, 'generic', options);
    }
  } catch (error) {
    log.warning('Job board fetch failed', {
      domain: board.domain,
      atsProvider: board.ats_provider,
      boardUrl: board.board_url,
      error: error instanceof Error ? error.message : String(error),
    });
  }

  return [];
}

async function fetchGreenhouseJobs(board, options) {
  const token = board.board_token || tokenFromBoardUrl(board.board_url);
  if (!token) {
    return [];
  }
  const apiUrl = `https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(token)}/jobs?content=true`;
  const payload = await fetchJson(apiUrl, options.requestTimeoutMs);
  return (payload.jobs || []).map((job) => normalizeGreenhouseJob(job, board, apiUrl)).filter(Boolean);
}

async function fetchLeverJobs(board, options) {
  const token = board.board_token || tokenFromBoardUrl(board.board_url);
  if (!token) {
    return [];
  }
  const apiUrl = `https://api.lever.co/v0/postings/${encodeURIComponent(token)}?mode=json`;
  const jobs = await fetchJson(apiUrl, options.requestTimeoutMs);
  return (Array.isArray(jobs) ? jobs : []).map((job) => normalizeLeverJob(job, board, apiUrl)).filter(Boolean);
}

async function fetchAshbyJobs(board, options) {
  const token = board.board_token || tokenFromBoardUrl(board.board_url);
  if (!token) {
    return [];
  }
  const apiUrl = `https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(token)}?includeCompensation=true`;
  const payload = await fetchJson(apiUrl, options.requestTimeoutMs);
  return (payload.jobs || []).map((job) => normalizeAshbyJob(job, board, apiUrl)).filter(Boolean);
}

async function fetchGenericHtmlJobs(board, provider, options) {
  const url = board.board_url || board.careers_url;
  if (!url) {
    return [];
  }
  const html = await fetchText(url, options.requestTimeoutMs);
  const $ = cheerio.load(html);
  const pageText = cleanText($('body').text());
  const linkJobs = extractJobLinks($, url, board, provider);
  if (linkJobs.length) {
    return linkJobs;
  }

  return extractJobTitlesFromText(pageText, url, board, provider);
}

function normalizeGreenhouseJob(job, board, apiUrl) {
  const location = job.location?.name ?? null;
  const description = htmlToText(job.content || '');
  return normalizeJob({
    board,
    atsProvider: 'greenhouse',
    externalJobId: String(job.id ?? job.absolute_url ?? job.title),
    title: job.title,
    department: job.departments?.[0]?.name ?? null,
    location,
    postedAt: job.first_published ?? job.updated_at ?? null,
    url: job.absolute_url,
    description,
    rawPayload: { api_url: apiUrl, job },
  });
}

function normalizeLeverJob(job, board, apiUrl) {
  const categories = job.categories || {};
  return normalizeJob({
    board,
    atsProvider: 'lever',
    externalJobId: String(job.id ?? job.hostedUrl ?? job.text),
    title: job.text,
    department: categories.department ?? null,
    location: categories.location ?? null,
    postedAt: job.createdAt ? new Date(job.createdAt).toISOString() : null,
    url: job.hostedUrl ?? job.applyUrl,
    description: htmlToText([job.description, job.descriptionPlain, job.additionalPlain].filter(Boolean).join('\n')),
    rawPayload: { api_url: apiUrl, job },
  });
}

function normalizeAshbyJob(job, board, apiUrl) {
  const location = Array.isArray(job.location) ? job.location.join(', ') : job.location;
  return normalizeJob({
    board,
    atsProvider: 'ashby',
    externalJobId: String(job.id ?? job.jobId ?? job.title),
    title: job.title,
    department: job.department ?? job.team ?? null,
    location,
    postedAt: job.publishedAt ?? job.publishedDate ?? job.createdAt ?? null,
    url: job.jobUrl ?? job.applyUrl,
    description: htmlToText(job.descriptionHtml || job.description || ''),
    rawPayload: { api_url: apiUrl, job },
  });
}

function extractJobLinks($, pageUrl, board, provider) {
  const jobs = [];
  $('a[href]').each((_index, element) => {
    const link = $(element);
    const title = cleanText(link.text());
    const href = normalizeAbsoluteUrl(link.attr('href'), pageUrl);
    if (!href || !looksLikeJobTitle(title)) {
      return;
    }

    const containerText = cleanText(link.closest('li, article, section, div').text());
    jobs.push(normalizeJob({
      board,
      atsProvider: provider,
      externalJobId: href,
      title,
      department: inferDepartment(containerText || title),
      location: inferLocation(containerText),
      postedAt: null,
      url: href,
      description: containerText,
      rawPayload: {
        extraction: 'html_link',
        page_url: pageUrl,
        text: containerText,
      },
    }));
  });

  return dedupeJobs(jobs.filter(Boolean));
}

function extractJobTitlesFromText(pageText, pageUrl, board, provider) {
  const lines = pageText.split(/[\n\r]+| {3,}/).map(cleanText).filter(Boolean);
  const jobs = [];

  for (const line of lines) {
    const title = line.replace(/\s+\|.*$/, '').replace(/\s+-\s+.*$/, '').trim();
    if (!looksLikeJobTitle(title)) {
      continue;
    }

    jobs.push(normalizeJob({
      board,
      atsProvider: provider,
      externalJobId: `${pageUrl}#${slugify(title)}`,
      title,
      department: inferDepartment(line),
      location: inferLocation(line),
      postedAt: null,
      url: pageUrl,
      description: line,
      rawPayload: {
        extraction: 'html_text',
        page_url: pageUrl,
        text: line,
      },
    }));
  }

  return dedupeJobs(jobs.filter(Boolean)).slice(0, 50);
}

function normalizeJob({
  board,
  atsProvider,
  externalJobId,
  title,
  department,
  location,
  postedAt,
  url,
  description,
  rawPayload,
}) {
  const cleanTitle = cleanText(title);
  const cleanUrl = url || board.board_url || board.careers_url;
  if (!cleanTitle || !cleanUrl) {
    return null;
  }

  const normalizedPostedAt = normalizeDateTime(postedAt);
  const now = new Date().toISOString();
  const textForInference = `${cleanTitle} ${department || ''} ${location || ''} ${description || ''}`;

  return {
    company_id: board.company_id ?? board.companyId ?? null,
    domain: normalizeDomain(board.domain || board.website),
    ats_provider: atsProvider,
    board_token: board.board_token ?? tokenFromBoardUrl(board.board_url) ?? null,
    board_url: board.board_url ?? board.careers_url ?? null,
    external_job_id: String(externalJobId || cleanUrl),
    title: cleanTitle,
    department: cleanText(department) || inferDepartment(textForInference),
    location: cleanText(location) || inferLocation(textForInference),
    remote_policy: inferRemotePolicy(textForInference),
    employment_type: inferEmploymentType(textForInference),
    posted_at: normalizedPostedAt,
    first_seen_at: normalizedPostedAt || now,
    last_seen_at: now,
    url: cleanUrl,
    description_text: cleanText(description).slice(0, 10000) || null,
    stack_terms: extractStackTerms(textForInference),
    seniority: inferSeniority(textForInference),
    is_active: true,
    raw_payload: {
      collector: 'ats-jobs-enricher',
      ...rawPayload,
    },
  };
}

async function fetchJson(url, requestTimeoutMs) {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(requestTimeoutMs),
    headers: {
      accept: 'application/json',
      'user-agent': 'VoidRadarATSJobsEnricher/0.1 (+mailto:hello@voidstudio.tech)',
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.json();
}

async function fetchText(url, requestTimeoutMs) {
  const response = await fetch(url, {
    redirect: 'follow',
    signal: AbortSignal.timeout(requestTimeoutMs),
    headers: {
      accept: 'text/html,application/xhtml+xml',
      'user-agent': 'VoidRadarATSJobsEnricher/0.1 (+mailto:hello@voidstudio.tech)',
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.text();
}

function htmlToText(value) {
  const firstPass = cheerio.load(value || '').text();
  const content = /<\/?[a-z][\s\S]*>/i.test(firstPass) ? firstPass : value;
  const $ = cheerio.load(content || '');
  $('br').replaceWith('\n');
  $('p, li').append('\n');
  return cleanText($.text());
}

function looksLikeJobTitle(value) {
  const title = cleanText(value);
  if (title.length < 4 || title.length > 120) {
    return false;
  }
  return /\b(engineer|developer|designer|product|data|platform|backend|frontend|full[- ]?stack|devops|qa|manager|analyst|architect|operations|automation)\b/i.test(title);
}

function inferDepartment(value) {
  const text = String(value || '').toLowerCase();
  if (/\b(engineering|developer|software|backend|frontend|platform|devops|qa|sre)\b/.test(text)) {
    return 'Engineering';
  }
  if (/\b(product manager|product designer|product)\b/.test(text)) {
    return 'Product';
  }
  if (/\b(data|analytics|machine learning|ai)\b/.test(text)) {
    return 'Data';
  }
  if (/\b(operations|automation|ops)\b/.test(text)) {
    return 'Operations';
  }
  return null;
}

function inferLocation(value) {
  const match = String(value || '').match(/\b(remote|hybrid|onsite|on-site|new york|london|san francisco|berlin|paris|amsterdam|antwerp|ontario|canada|united states|usa|us)\b/i);
  return match ? match[0] : null;
}

function inferRemotePolicy(value) {
  const text = String(value || '').toLowerCase();
  if (text.includes('remote')) {
    return 'remote';
  }
  if (text.includes('hybrid')) {
    return 'hybrid';
  }
  if (text.includes('onsite') || text.includes('on-site')) {
    return 'onsite';
  }
  return null;
}

function inferEmploymentType(value) {
  const text = String(value || '').toLowerCase();
  if (text.includes('part-time') || text.includes('part time')) {
    return 'part_time';
  }
  if (text.includes('contract')) {
    return 'contract';
  }
  if (/\bintern(ship)?\b/.test(text)) {
    return 'internship';
  }
  if (text.includes('full-time') || text.includes('full time')) {
    return 'full_time';
  }
  return null;
}

function inferSeniority(value) {
  const text = String(value || '').toLowerCase();
  if (/\b(staff|principal|lead)\b/.test(text)) {
    return 'staff';
  }
  if (/\b(senior|sr\.?)\b/.test(text)) {
    return 'senior';
  }
  if (/\b(junior|jr\.?|entry)\b/.test(text)) {
    return 'junior';
  }
  return null;
}

function extractStackTerms(value) {
  const text = String(value || '').toLowerCase();
  return STACK_TERMS.filter((term) => text.includes(term)).sort();
}

function dedupeJobs(jobs) {
  const seen = new Set();
  const unique = [];
  for (const job of jobs) {
    const key = `${job.domain}:${job.ats_provider}:${job.external_job_id}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(job);
  }
  return unique;
}

function tokenFromBoardUrl(value) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    const part = url.pathname.split('/').filter(Boolean)[0];
    return part ? decodeURIComponent(part).toLowerCase() : null;
  } catch {
    return null;
  }
}

function normalizeProvider(value) {
  const provider = String(value || 'generic').toLowerCase();
  return ['greenhouse', 'lever', 'ashby', 'workable', 'generic'].includes(provider)
    ? provider
    : 'generic';
}

function normalizeDateTime(value) {
  if (!value) {
    return null;
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Date(timestamp).toISOString();
}

function normalizeAbsoluteUrl(value, baseUrl) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value, baseUrl);
    if (!['http:', 'https:'].includes(url.protocol)) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
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

function slugify(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
