"""Real gallery/navigation with 20 temporary charts; no scientific/model work."""
import asyncio
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_preparation as prep
import server
from playwright.async_api import async_playwright

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG9sAAAAASUVORK5CYII=')


async def check(url, renders):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport={'width':1440,'height':1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        cached = set(); last_thumbnail = asyncio.Event()
        def response(response):
            if 'cached_only=1' in response.url:
                cached.add(response.url.split('/charts/')[1].split('/')[0])
                if 'chart20' in cached:
                    last_thumbnail.set()
        page.on('response', response)
        await page.route('**/api/collaboration**', lambda route: route.fulfill(json={
            'configured':False,'connected':False,'revision':'test','author':'test','files':0}))
        try:
            await page.goto(url, wait_until='domcontentloaded')
            await page.wait_for_function('state.projects.length > 0')
            assert renders == [], renders
            await page.locator('#workspaceRecent').select_option('foraging')
            await page.locator('#workspaceResume').click()
            await page.wait_for_function('state.chart === "chart01" && state.detail !== null')
            await page.locator('.chartCard[data-chart="chart01"] img').wait_for()
            assert renders == ['# chart01'], renders
            assert await page.locator('.chartCard').count() == 20
            await page.locator('.chartCard[data-chart="chart20"]').scroll_into_view_if_needed()
            await asyncio.wait_for(last_thumbnail.wait(), 10)
            assert renders == ['# chart01'], renders
            await page.locator('.chartCard[data-chart="chart05"] .chartOpen').click()
            await page.locator('.chartCard[data-chart="chart05"] img').wait_for()
            assert renders == ['# chart01','# chart05'], renders
            assert not errors, errors
            print(json.dumps({'charts':20,'rendered_only':['chart01','chart05'],
                'unselected_gallery_renders':0,'startup_renders':0,'cached_thumbnail_requests':len(cached),'errors':errors}))
        finally:
            await browser.close()


def main():
    with ExitStack() as stack:
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='gallery-demand-test-')))
        projects = root/'projects'; project = projects/'foraging'
        (project/'charts').mkdir(parents=True); (project/'data').mkdir()
        figures = []
        for index in range(1,21):
            name = f'chart{index:02}'
            (project/'charts'/(name+'.py')).write_text('# '+name)
            figures.append({'figure_id':name})
        prep.write_json(project/'project.json', {'name':'foraging','data_source_type':'universal_plot'})
        prep.save_state(project, {'status':'ready','mode':'direct','figures':figures,'validation':{'state':'passed'}})
        stack.enter_context(patch.object(server,'PROJECTS',projects))
        stack.enter_context(patch.object(server.Handler,'log_message',lambda *args:None))
        renders = []
        def render(project, source):
            renders.append(source)
            return PNG
        stack.enter_context(patch.object(server,'render',side_effect=render))
        http = server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        stack.callback(http.server_close); stack.callback(http.shutdown)
        stack.enter_context(patch.dict(os.environ,{'CHART_STUDIO_PORT':str(http.server_port)}))
        threading.Thread(target=http.serve_forever,daemon=True).start()
        asyncio.run(check(f'http://127.0.0.1:{http.server_port}/', renders))


if __name__ == '__main__':
    main()
