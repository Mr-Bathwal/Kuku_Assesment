// docs/_solution.html -> docs/SOLUTION.pdf  (A4, print styles live in the HTML)
const { chromium } = require('playwright-core');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage();
  const file = 'file:///' + path.resolve('docs/_solution.html').split(path.sep).join('/');
  await page.goto(file, { waitUntil: 'networkidle' });
  await page.pdf({
    path: 'docs/SOLUTION.pdf',
    format: 'A4',
    printBackground: true,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });
  await browser.close();
  console.log('pdf written');
})();
