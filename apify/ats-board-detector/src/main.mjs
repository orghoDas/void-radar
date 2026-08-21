import { Actor, log } from 'apify';
import * as cheerio from 'cheerio';

const DEFAULT_COMPANIES = [
  { company_id: null, domain: 'snout.com' },
  { company_id: null, domain: 'marpledata.com' },
];

const CAREERS_PATHS = [
  '/careers',
  '/jobs',
  '/join-us',
  '/work-with-us',
  '/company/careers',
];

// Board URLs are harvested from a[href], iframe[src] and script[src], so an
// embed widget such as .../embed.js yields a "token" of "embed" or "js". These
// path segments are never a company board slug.
const RESERVED_BOARD_TOKENS = new Set([
  'js', 'css', 'json', 'api', 'embed', 'embeds', 'widget', 'widgets',
  'static', 'assets', 'cdn', 'img', 'images', 'fonts', 'script', 'scripts',
  'style', 'styles', 'dist', 'build', 'public', 'favicon', 'robots',
]);

const ASSET_EXTENSION_PATTERN = /\.(js|mjs|css|json|map|png|jpe?g|svg|gif|ico|woff2?|txt|xml)$/i;

function isValidBoardToken(token) {
  if (!token || token.length < 2) {
    return false;
  }
  if (ASSET_EXTENSION_PATTERN.test(token)) {
    return false;
  }
  if (RESERVED_BOARD_TOKENS.has(token)) {
    return false;
  }
  return /^[a-z0-9][a-z0-9._-]*$/.test(token);
}

// A board reached through an outbound link may belong to a VC, parent, or
// partner rather than this company. We cannot tell a rebrand from a third party
// automatically, so record the mismatch and let the backend route it to review.
function boardTokenMatchesDomain(token, domain) {
  const slug = String(token || '').replace(/[^a-z0-9]/g, '');
  const host = String(domain || '').split('.')[0].replace(/[^a-z0-9]/g, '');
  if (!slug || !host) {
    return false;
  }
  return slug.includes(host) || host.includes(slug) || slug.slice(0, 5) === host.slice(0, 5);
}

const PROVIDERS = {
  greenhouse: {
    hostPatterns: ['boards.greenhouse.io', 'job-boards.greenhouse.io'],
    pathTokenIndex: 0,
  },
  lever: {
    hostPatterns: ['jobs.lever.co'],
    pathTokenIndex: 0,
  },
  ashby: {
    hostPatterns: ['jobs.ashbyhq.com'],
    pathTokenIndex: 0,
  },
  workable: {
    hostPatterns: ['apply.workable.com'],
    pathTokenIndex: 0,
  },
};

await Actor.main(async () => {
  const input = (await Actor.getInput()) ?? {};
  const companies = Array.isArray(input.companies) && input.companies.length
    ? input.companies
    : DEFAULT_COMPANIES;
  const maxItems = Number(input.maxItems ?? 100);
  const requestDelayMs = Number(input.requestDelayMs ?? 250);
  const requestTimeoutMs = Number(input.requestTimeoutMs ?? 8000);
  const maxCareersUrls = Number(input.maxCareersUrls ?? 8);
  const includeGenericCareers = input.includeGenericCareers !== false;
  const emitMissesToDataset = Boolean(input.emitMissesToDataset ?? false);

  log.info('Starting ATS board detection', {
    companyCount: companies.length,
    maxItems,
    includeGenericCareers,
    emitMissesToDataset,
  });

  const detections = [];
  const misses = [];

  for (const company of companies.slice(0, maxItems)) {
    const domain = normalizeDomain(company.domain || company.website);
    if (!domain) {
      misses.push(missRecord(company, null, null, [], 'invalid_domain'));
      continue;
    }

    const result = await probeCompany({
      companyId: company.company_id ?? company.companyId ?? null,
      domain,
      includeGenericCareers,
      requestTimeoutMs,
      maxCareersUrls,
    });

    if (result.detections.length) {
      detections.push(...result.detections);
      await Actor.pushData(result.detections);
    } else {
      const miss = missRecord(
        company,
        domain,
        result.careersUrl,
        result.checkedUrls,
        'no_supported_ats_found'
      );
      misses.push(miss);
      if (emitMissesToDataset) {
        await Actor.pushData([{ ...miss, record_type: 'miss' }]);
      }
    }

    await Actor.setValue('STATE', {
      lastDomain: domain,
      detectionsOutput: detections.length,
      missesOutput: misses.length,
    });
    await sleep(requestDelayMs);
  }

  await Actor.setValue('ATS_MISSES', misses);
  log.info('ATS board detection finished', {
    detectionsOutput: detections.length,
    missesOutput: misses.length,
  });
});

async function probeCompany({
  companyId,
  domain,
  includeGenericCareers,
  requestTimeoutMs,
  maxCareersUrls,
}) {
  const checkedUrls = [];
  const pages = [];
  const baseUrl = `https://${domain}`;
  const homepage = await fetchPage(baseUrl, { requestTimeoutMs });
  checkedUrls.push(baseUrl);
  if (homepage.ok) {
    pages.push(homepage);
  }

  const candidateCareersUrls = careersCandidates(domain, homepage.html, maxCareersUrls);
  for (const url of candidateCareersUrls) {
    if (checkedUrls.includes(url)) {
      continue;
    }
    checkedUrls.push(url);
    const page = await fetchPage(url, { requestTimeoutMs });
    if (page.ok) {
      pages.push(page);
    }
  }

  const detections = [];
  for (const page of pages) {
    for (const detection of detectProviderBoards(page, { companyId, domain, checkedUrls })) {
      detections.push(detection);
    }
  }

  const uniqueDetections = dedupeDetections(detections);
  if (uniqueDetections.length) {
    return {
      detections: uniqueDetections,
      careersUrl: firstCareersUrl(pages),
      checkedUrls,
    };
  }

  const careersPage = pages.find((page) => page.kind === 'careers');
  if (includeGenericCareers && careersPage) {
    return {
      detections: [
        genericCareersDetection({
          companyId,
          domain,
          careersPage,
          checkedUrls,
        }),
      ],
      careersUrl: careersPage.url,
      checkedUrls,
    };
  }

  return {
    detections: [],
    careersUrl: firstCareersUrl(pages),
    checkedUrls,
  };
}

function careersCandidates(domain, homepageHtml, maxCareersUrls) {
  const candidates = new Set(CAREERS_PATHS.map((path) => `https://${domain}${path}`));
  if (!homepageHtml) {
    return [...candidates];
  }

  const $ = cheerio.load(homepageHtml);
  $('a[href]').each((_index, element) => {
    const href = $(element).attr('href');
    const text = $(element).text().toLowerCase();
    const absoluteUrl = normalizeAbsoluteUrl(href, `https://${domain}`);
    if (!absoluteUrl) {
      return;
    }

    const normalizedHref = absoluteUrl.toLowerCase();
    if (
      text.includes('career') ||
      text.includes('jobs') ||
      normalizedHref.includes('/careers') ||
      normalizedHref.includes('/jobs') ||
      isSupportedAtsUrl(absoluteUrl)
    ) {
      candidates.add(absoluteUrl);
    }
  });

  return [...candidates].slice(0, maxCareersUrls);
}

function detectProviderBoards(page, { companyId, domain, checkedUrls }) {
  const detections = [];
  const $ = cheerio.load(page.html);
  const urls = new Set([page.url]);

  $('a[href], iframe[src], script[src]').each((_index, element) => {
    const rawUrl = $(element).attr('href') || $(element).attr('src');
    const absoluteUrl = normalizeAbsoluteUrl(rawUrl, page.url);
    if (absoluteUrl) {
      urls.add(absoluteUrl);
    }
  });

  for (const url of urls) {
    const provider = providerFromUrl(url);
    if (!provider) {
      continue;
    }

    detections.push({
      company_id: companyId,
      domain,
      ats_provider: provider.name,
      board_token: provider.token,
      board_url: provider.boardUrl,
      careers_url: page.kind === 'careers' ? page.url : null,
      confidence: page.url === provider.boardUrl ? 0.98 : 0.92,
      evidence_url: page.url,
      raw_evidence: {
        collector: 'ats-board-detector',
        detection_method: page.url === provider.boardUrl ? 'direct_board_url' : 'page_link',
        token_matches_domain: boardTokenMatchesDomain(provider.token, domain),
        matched_url: url,
        checked_urls: checkedUrls,
        page_status: page.status,
      },
    });
  }

  return detections;
}

function providerFromUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }

  const hostname = url.hostname.toLowerCase().replace(/^www\./, '');
  const pathParts = url.pathname.split('/').filter(Boolean);

  for (const [name, config] of Object.entries(PROVIDERS)) {
    if (!config.hostPatterns.includes(hostname)) {
      continue;
    }
    const rawToken = pathParts[config.pathTokenIndex];
    if (!rawToken) {
      continue;
    }
    const token = decodeURIComponent(rawToken).toLowerCase();
    if (!isValidBoardToken(token)) {
      continue;
    }
    return {
      name,
      token,
      boardUrl: `${url.protocol}//${hostname}/${rawToken}`,
    };
  }

  return null;
}

function genericCareersDetection({ companyId, domain, careersPage, checkedUrls }) {
  return {
    company_id: companyId,
    domain,
    ats_provider: 'generic',
    board_token: normalizeGenericBoardToken(careersPage.url),
    board_url: careersPage.url,
    careers_url: careersPage.url,
    confidence: 0.55,
    evidence_url: careersPage.url,
    raw_evidence: {
      collector: 'ats-board-detector',
      detection_method: 'generic_careers_page',
      checked_urls: checkedUrls,
      page_status: careersPage.status,
    },
  };
}

function missRecord(company, domain, careersUrl, checkedUrls, reason) {
  return {
    company_id: company.company_id ?? company.companyId ?? null,
    domain,
    careers_url: careersUrl,
    evidence_url: careersUrl || (domain ? `https://${domain}` : null),
    confidence: reason === 'invalid_domain' ? 0.2 : 0.7,
    raw_evidence: {
      collector: 'ats-board-detector',
      reason,
      input: company,
      checked_urls: checkedUrls,
    },
  };
}

async function fetchPage(url, { requestTimeoutMs }) {
  try {
    const response = await fetch(url, {
      redirect: 'follow',
      signal: AbortSignal.timeout(requestTimeoutMs),
      headers: {
        accept: 'text/html,application/xhtml+xml',
        'user-agent': 'VoidRadarATSBoardDetector/0.1 (+mailto:hello@voidstudio.tech)',
      },
    });
    const contentType = response.headers.get('content-type') || '';
    const html = contentType.includes('text/html') ? await response.text() : '';
    return {
      ok: response.ok && Boolean(html),
      url: response.url || url,
      requestedUrl: url,
      status: response.status,
      html,
      kind: isCareersLikeUrl(response.url || url) ? 'careers' : 'homepage',
    };
  } catch (error) {
    log.debug('Page fetch failed', {
      url,
      error: error instanceof Error ? error.message : String(error),
    });
    return {
      ok: false,
      url,
      requestedUrl: url,
      status: null,
      html: '',
      kind: isCareersLikeUrl(url) ? 'careers' : 'homepage',
    };
  }
}

function firstCareersUrl(pages) {
  return pages.find((page) => page.kind === 'careers')?.url ?? null;
}

function dedupeDetections(detections) {
  const seen = new Set();
  const unique = [];
  for (const detection of detections) {
    const key = `${detection.domain}:${detection.ats_provider}:${detection.board_token}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(detection);
  }
  return unique;
}

function isSupportedAtsUrl(value) {
  return Boolean(providerFromUrl(value));
}

function isCareersLikeUrl(value) {
  const lower = String(value || '').toLowerCase();
  return lower.includes('/career') || lower.includes('/jobs') || isSupportedAtsUrl(lower);
}

function normalizeGenericBoardToken(value) {
  const url = new URL(value);
  return `${url.hostname}${url.pathname}`.replace(/^www\./, '').replace(/\/$/, '').toLowerCase();
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

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
