#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const PROJECT_DIR = path.resolve(__dirname, "..");
const DEFAULT_URL = "https://uutistenlukija.fi/";
const DEFAULT_OUTPUT_DIR = path.join(PROJECT_DIR, "artifacts", "visual-qa-monitor");
const DEFAULT_LOG = path.join(PROJECT_DIR, "pipeline", "logs", "visual-qa-monitor.log");
const FALLBACK_CHROMIUM_PATH = "/home/pertt/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome";
const SYSTEM_CHROMIUM_PATHS = [
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];
const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 1000, colorScheme: "light" },
  { name: "mobile-390", width: 390, height: 844, colorScheme: "light" },
  { name: "mobile-390-dark", width: 390, height: 844, colorScheme: "dark" },
];
const MONITORED_CONTRAST_SELECTORS = [
  ".portal-livebar time",
  ".portal-teaser .portal-kicker",
  ".portal-row-card .portal-kicker",
  ".portal-newsletter h2",
  ".portal-newsletter p",
  ".portal-newsletter label",
  ".portal-newsletter input",
  ".portal-newsletter button",
];

function parseArgs(argv) {
  const args = {
    url: DEFAULT_URL,
    outputDir: DEFAULT_OUTPUT_DIR,
    logPath: DEFAULT_LOG,
    postDiscord: false,
    selfTest: false,
  };
  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--url") args.url = argv[++index];
    else if (arg === "--output-dir") args.outputDir = path.resolve(argv[++index]);
    else if (arg === "--log") args.logPath = path.resolve(argv[++index]);
    else if (arg === "--post-discord") args.postDiscord = true;
    else if (arg === "--self-test") args.selfTest = true;
    else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function timestampSlug(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function appendLog(logPath, message) {
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${message}\n`);
}

function chromiumLaunchOptions() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    FALLBACK_CHROMIUM_PATH,
    ...SYSTEM_CHROMIUM_PATHS,
  ].filter(Boolean);
  try {
    candidates.unshift(chromium.executablePath());
  } catch (_error) {
    // Playwright can still launch when a host Chrome path is provided below.
  }

  const existing = candidates.find((candidate) => fs.existsSync(candidate));
  const options = {
    headless: true,
    args: ["--no-sandbox"],
  };
  if (existing) options.executablePath = existing;
  return options;
}

function summarizeIssues(results) {
  const issues = [];
  for (const result of results) {
    for (const issue of result.issues) {
      issues.push(`${result.viewport}: ${issue}`);
    }
  }
  return issues;
}

function colorChannelToLinear(value) {
  const normalized = value / 255;
  return normalized <= 0.03928
    ? normalized / 12.92
    : Math.pow((normalized + 0.055) / 1.055, 2.4);
}

function relativeLuminance(rgb) {
  const [r, g, b] = rgb.map(colorChannelToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(foreground, background) {
  const fg = relativeLuminance(foreground);
  const bg = relativeLuminance(background);
  const lighter = Math.max(fg, bg);
  const darker = Math.min(fg, bg);
  return (lighter + 0.05) / (darker + 0.05);
}

function normalizeImageSource(value, baseUrl = DEFAULT_URL) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw, baseUrl);
    const pathname = parsed.pathname.replace(/\/{2,}/g, "/");
    const hostname = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const port = parsed.port ? `:${parsed.port}` : "";
    return `${parsed.protocol.toLowerCase()}//${hostname}${port}${pathname}`;
  } catch (_error) {
    return raw.split(/[?#]/, 1)[0];
  }
}

function riverCategoryFallbackIssues(imageSources, baseUrl = DEFAULT_URL) {
  const normalized = imageSources
    .slice(0, 12)
    .map((source) => normalizeImageSource(source, baseUrl));
  const fallbacks = normalized.map((source) => (
    source.includes("/images/categories/") ? source : ""
  ));
  const issues = [];
  const consecutive = new Set();
  for (let index = 1; index < fallbacks.length; index += 1) {
    if (fallbacks[index] && fallbacks[index] === fallbacks[index - 1]) {
      consecutive.add(fallbacks[index]);
    }
  }
  for (const source of consecutive) {
    issues.push(`river category fallback repeated in consecutive cards ${source}`);
  }

  const counts = new Map();
  for (const source of fallbacks) {
    if (!source) continue;
    counts.set(source, (counts.get(source) || 0) + 1);
  }
  for (const [source, count] of counts) {
    if (count >= 3) {
      issues.push(`river category fallback repeated ${count}/${normalized.length} cards ${source}`);
    }
  }
  return issues;
}

function homepageArticleImageIssues(imageSources) {
  return imageSources.some((source) => String(source || "").trim())
    ? []
    : ["homepage has zero visible article images"];
}

function selfTest() {
  const whiteBlack = contrastRatio([255, 255, 255], [0, 0, 0]);
  const same = contrastRatio([10, 10, 10], [10, 10, 10]);
  if (whiteBlack < 20.9 || whiteBlack > 21.1) {
    throw new Error(`Unexpected black/white contrast: ${whiteBlack}`);
  }
  if (same !== 1) {
    throw new Error(`Unexpected same-color contrast: ${same}`);
  }
  const slug = timestampSlug(new Date("2026-06-03T22:00:00Z"));
  if (slug !== "20260603T220000Z") {
    throw new Error(`Unexpected timestamp slug: ${slug}`);
  }

  const talousFallback = "/images/categories/talous.jpg";
  const currentPattern = [
    talousFallback,
    "https://www.uutistenlukija.fi/images/categories/talous.jpg?cache=1",
    talousFallback,
    talousFallback,
    "/images/articles/distinct-a.jpg",
    talousFallback,
    talousFallback,
    "/images/articles/distinct-b.jpg",
    talousFallback,
    talousFallback,
    talousFallback,
    talousFallback,
  ];
  const currentIssues = riverCategoryFallbackIssues(currentPattern);
  if (!currentIssues.some((issue) => issue.includes("consecutive cards"))) {
    throw new Error(`Current river fixture did not trigger consecutive fallback: ${currentIssues}`);
  }
  if (!currentIssues.some((issue) => issue.includes("10/12 cards"))) {
    throw new Error(`Current river fixture did not trigger 10/12 fallback: ${currentIssues}`);
  }
  const imageFreeIssues = homepageArticleImageIssues([]);
  if (!imageFreeIssues.some((issue) => issue.includes("zero visible article images"))) {
    throw new Error(`Image-free homepage fixture did not fail: ${imageFreeIssues}`);
  }
  const illustratedIssues = homepageArticleImageIssues(["/images/categories/talous.jpg"]);
  if (illustratedIssues.length !== 0) {
    throw new Error(`Illustrated homepage fixture unexpectedly failed: ${illustratedIssues}`);
  }
}

async function inspectPage(page) {
  return page.evaluate(({ selectors }) => {
    function parseRgb(value) {
      const match = String(value || "").match(/rgba?\(([^)]+)\)/);
      if (!match) return null;
      const parts = match[1].split(",").map((part) => Number.parseFloat(part.trim()));
      if (parts.length < 3) return null;
      return { rgb: parts.slice(0, 3), alpha: parts.length >= 4 ? parts[3] : 1 };
    }

    function visible(element) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden"
        && style.display !== "none"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0;
    }

    function backgroundFor(element) {
      let current = element;
      while (current) {
        const parsed = parseRgb(window.getComputedStyle(current).backgroundColor);
        if (parsed && parsed.alpha > 0.95) return parsed.rgb;
        current = current.parentElement;
      }
      const body = parseRgb(window.getComputedStyle(document.body).backgroundColor);
      return body ? body.rgb : [255, 255, 255];
    }

    function luminance(rgb) {
      function channel(value) {
        const normalized = value / 255;
        return normalized <= 0.03928
          ? normalized / 12.92
          : Math.pow((normalized + 0.055) / 1.055, 2.4);
      }
      return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
    }

    function contrast(foreground, background) {
      const fg = luminance(foreground);
      const bg = luminance(background);
      return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    }

    const body = document.body;
    const root = document.documentElement;
    const issues = [];
    const requiredSelectors = ["header", "nav", "main"];
    for (const selector of requiredSelectors) {
      if (!document.querySelector(selector)) {
        issues.push(`missing required selector ${selector}`);
      }
    }

    const horizontalOverflow = Math.max(body.scrollWidth, root.scrollWidth) - root.clientWidth;
    if (horizontalOverflow > 2) {
      issues.push(`horizontal overflow ${horizontalOverflow}px`);
    }

    const brokenImages = Array.from(document.images)
      .filter((img) => visible(img) && (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0))
      .map((img) => img.currentSrc || img.src || img.alt || "unknown image")
      .slice(0, 10);
    for (const image of brokenImages) {
      issues.push(`broken visible image ${image}`);
    }

    function imageSource(img) {
      return img ? String(img.currentSrc || img.src || img.getAttribute("src") || "") : "";
    }

    function isCategoryFallbackImage(img) {
      const src = imageSource(img);
      return src.includes("/images/categories/");
    }

    const leadImage = document.querySelector(".portal-lead__image img");
    if (leadImage && visible(leadImage) && isCategoryFallbackImage(leadImage)) {
      issues.push(`prominent homepage fallback image lead ${imageSource(leadImage)}`);
    }

    const teaserFallbacks = Array.from(document.querySelectorAll(".portal-teaser__thumb img"))
      .filter(visible)
      .filter(isCategoryFallbackImage)
      .map((img) => imageSource(img))
      .slice(0, 4);
    if (teaserFallbacks.length > 1) {
      issues.push(`prominent homepage fallback images in ${teaserFallbacks.length} top teasers`);
    }

    const visibleArticleImageSources = Array.from(document.querySelectorAll(
      ".portal-lead__image img, .portal-teaser__thumb img, .portal-river .portal-row-card img",
    ))
      .filter(visible)
      .map((img) => imageSource(img));
    if (visibleArticleImageSources.length === 0) {
      issues.push("homepage has zero visible article images");
    }

    const failedFallbacks = Array.from(document.querySelectorAll(".portal-lead__image .img-failed, .portal-teaser__thumb .img-failed"))
      .filter(visible)
      .length;
    if (failedFallbacks > 0) {
      issues.push(`homepage image fallback error state on ${failedFallbacks} prominent slots`);
    }

    const riverCardImageSources = Array.from(document.querySelectorAll(".portal-river .portal-row-card"))
      .slice(0, 12)
      .map((card) => {
        const img = card.querySelector("img");
        return img && visible(img) ? imageSource(img) : "";
      });

    const overflowingElements = Array.from(document.querySelectorAll("a,h1,h2,h3,p,li,button,input,textarea,select"))
      .filter(visible)
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        if (rect.right < -2 || rect.left > root.clientWidth + 2) return false;
        return rect.left < -2 || rect.right > root.clientWidth + 2;
      })
      .slice(0, 10)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return `${element.tagName.toLowerCase()} ${Math.round(rect.left)}..${Math.round(rect.right)}`;
      });
    for (const element of overflowingElements) {
      issues.push(`visible element overflow ${element}`);
    }

    const contrastChecks = [];
    for (const selector of selectors) {
      const elements = Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, 8);
      for (const element of elements) {
        const color = parseRgb(window.getComputedStyle(element).color);
        if (!color) continue;
        const ratio = contrast(color.rgb, backgroundFor(element));
        contrastChecks.push({
          selector,
          text: (element.textContent || "").trim().slice(0, 80),
          ratio: Number(ratio.toFixed(2)),
        });
        if (ratio < 4.5) {
          issues.push(`low contrast ${selector} ratio ${ratio.toFixed(2)}`);
        }
      }
    }

    return {
      title: document.title,
      url: window.location.href,
      requiredSelectors,
      horizontalOverflow,
      brokenImages,
      visibleArticleImageCount: visibleArticleImageSources.length,
      riverCardCount: riverCardImageSources.length,
      riverCardImageSources,
      overflowingElements,
      contrastChecks,
      issues,
    };
  }, { selectors: MONITORED_CONTRAST_SELECTORS });
}

async function loadLazyMedia(page) {
  await page.evaluate(async () => {
    for (const image of document.images) {
      image.loading = "eager";
      image.decoding = "async";
    }
    const step = Math.max(window.innerHeight * 0.75, 300);
    const wait = (ms) => new Promise((resolve) => {
      window.setTimeout(resolve, ms);
    });
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await wait(150);
    }
    window.scrollTo(0, 0);
    await Promise.race([
      Promise.all(Array.from(document.images).map((image) => (
        image.complete ? Promise.resolve() : new Promise((resolve) => {
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", resolve, { once: true });
        })
      ))),
      wait(5000),
    ]);
    await wait(250);
  });
}

async function postDiscord(report) {
  const webhook = process.env.DISCORD_OPERATIONS_WEBHOOK
    || process.env.DISCORD_PIPELINE_WEBHOOK
    || process.env.DISCORD_WEBHOOK_OPS;
  if (!webhook) return false;
  const issues = summarizeIssues(report.results).slice(0, 8);
  const content = [
    `OPE-157 visual QA monitor failed for ${report.url}`,
    `Run: ${report.runId}`,
    `Report: ${report.reportPath}`,
    ...issues.map((issue) => `- ${issue}`),
  ].join("\n");
  const response = await fetch(webhook, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return response.ok;
}

async function runMonitor(args) {
  const runId = timestampSlug();
  const runDir = path.join(args.outputDir, runId);
  fs.mkdirSync(runDir, { recursive: true });

  const launchOptions = chromiumLaunchOptions();
  const browser = await chromium.launch(launchOptions);
  const results = [];
  try {
    for (const viewport of VIEWPORTS) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: viewport.colorScheme,
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();
      const response = await page.goto(args.url, { waitUntil: "networkidle", timeout: 45000 });
      await loadLazyMedia(page);
      await page.screenshot({
        path: path.join(runDir, `${viewport.name}.png`),
        fullPage: true,
      });
      const details = await inspectPage(page);
      const status = response ? response.status() : 0;
      const issues = [
        ...details.issues,
        ...riverCategoryFallbackIssues(details.riverCardImageSources, details.url),
      ];
      if (status < 200 || status >= 400) issues.push(`HTTP status ${status}`);
      results.push({
        viewport: viewport.name,
        width: viewport.width,
        height: viewport.height,
        colorScheme: viewport.colorScheme,
        httpStatus: status,
        screenshot: path.join(runDir, `${viewport.name}.png`),
        ...details,
        issues,
      });
      await context.close();
    }
  } finally {
    await browser.close();
  }

  const reportPath = path.join(runDir, "summary.json");
  const report = {
    ok: results.every((result) => result.issues.length === 0),
    runId,
    checkedAt: new Date().toISOString(),
    url: args.url,
    viewports: VIEWPORTS.map((viewport) => viewport.name),
    reportPath,
    browserExecutable: launchOptions.executablePath || "playwright-default",
    results,
  };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  appendLog(args.logPath, `run=${runId} ok=${report.ok} report=${reportPath}`);
  if (!report.ok && args.postDiscord) {
    try {
      report.discordPosted = await postDiscord(report);
      fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    } catch (error) {
      appendLog(args.logPath, `discord_post_failed ${error.message}`);
    }
  }
  console.log(JSON.stringify({
    ok: report.ok,
    runId: report.runId,
    reportPath: report.reportPath,
    issues: summarizeIssues(results),
  }, null, 2));
  return report.ok ? 0 : 1;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.selfTest) {
    selfTest();
    console.log(JSON.stringify({ ok: true, selfTest: true }));
    return 0;
  }
  return runMonitor(args);
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
