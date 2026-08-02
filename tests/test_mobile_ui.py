"""
Real browser layout tests - these properties (do 3 badges stay on the same
line? are touch targets tall enough?) can't be verified from raw HTML
alone, only from actual rendered layout, so this uses Playwright against
a live Flask dev server instead of the usual test client.
"""
import subprocess
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVER_SCRIPT = """
import sys, os, tempfile
sys.path.insert(0, '{webapp_dir}')
os.chdir('{webapp_dir}')
import app as app_module
from core import db as dbmod
TMP_DB = tempfile.mktemp(suffix='.db')
dbmod.init_db(db_path=TMP_DB, data_dir='data')
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.run(host='127.0.0.1', port=5098, debug=False)
""".format(webapp_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

script_path = "/tmp/test_server_5098.py"
with open(script_path, "w") as f:
    f.write(SERVER_SCRIPT)

proc = subprocess.Popen([sys.executable, script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

node_script = """
const { chromium } = require('/home/claude/.npm-global/lib/node_modules/playwright');

let failures = 0;
function check(label, cond) {
  console.log(`    [${cond ? "OK" : "FAIL"}] ${label}`);
  if (!cond) failures++;
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
  await page.goto('http://127.0.0.1:5098/profiles', { waitUntil: 'networkidle' });
  await page.fill('input[name=name]', 'Fadi');
  await page.click('button[type=submit]');
  await page.waitForLoadState('networkidle');

  console.log("[1] Bottom nav: all 9 items meet 44px minimum touch target...");
  const items = await page.locator('.bottomnav a').all();
  check(`exactly 9 nav items (got ${items.length})`, items.length === 9);
  let allTall = true, allHaveIcons = true;
  for (const item of items) {
    const box = await item.boundingBox();
    if (box.height < 44) allTall = false;
    if (!(await item.locator('svg').isVisible())) allHaveIcons = false;
  }
  check("all 9 items >= 44px tall", allTall);
  check("all 9 items have a visible icon", allHaveIcons);
  const navBox = await page.locator('.bottomnav').boundingBox();
  check(`nav fits within 375px viewport width (got ${navBox.width})`, navBox.width <= 375);

  console.log("[2] Library badges (category/tier/type) stay grouped together...");
  for (const cat of ['conditioning', 'handstand', 'pull']) {
    await page.goto('http://127.0.0.1:5098/library?category=' + cat, { waitUntil: 'networkidle' });
    const rows = await page.locator('.exercise-row-v2').all();
    for (let i = 0; i < Math.min(rows.length, 3); i++) {
      const row = rows[i];
      const catBox = await row.locator('.category-badge').boundingBox();
      const tierBox = await row.locator('.tier-badge').boundingBox();
      const roleBox = await row.locator('.role-tag').boundingBox();
      const sameLine = Math.abs(catBox.y - tierBox.y) < 2 && Math.abs(tierBox.y - roleBox.y) < 2;
      check(`${cat} row ${i}: category+tier+role all on the same line`, sameLine);
    }
  }

  console.log("[3] Classification vocabulary matches what was requested...");
  await page.goto('http://127.0.0.1:5098/library?category=warmup', { waitUntil: 'networkidle' });
  let html = await page.content();
  check("warm-up items now show 'extra' as their type classification", html.includes('>extra<'));
  check("no leftover 'warm-up' hyphenated label as a type badge", !html.includes('role-tag role-warmup'));

  await browser.close();
  if (failures > 0) { console.log(`\\n${failures} CHECK(S) FAILED`); process.exit(1); }
  console.log("\\nALL MOBILE UI TESTS PASSED (real headless Chromium)");
})();
"""

node_script_path = "/tmp/test_mobile_ui.js"
with open(node_script_path, "w") as f:
    f.write(node_script)

result = subprocess.run(["node", node_script_path])
proc.terminate()
proc.wait()
sys.exit(result.returncode)
