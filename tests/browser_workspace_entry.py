"""Real browser regression for entering a partially prepared project.

Uses temporary projects, no model calls and no actual rendering. The initial
project request is held until the user has entered another project, exercising
the startup/explicit-navigation race without timing assumptions.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import project_preparation as prep
from playwright.async_api import async_playwright


async def check(url):
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(executable_path='/usr/bin/google-chrome',
                                                headless=True,args=['--no-sandbox'])
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        started=asyncio.Event();release=asyncio.Event();finished=asyncio.Event()
        requests=0
        async def projects(route):
            nonlocal requests
            requests+=1
            ordinal=requests
            response=await route.fetch()
            if ordinal==1:
                started.set()
                await release.wait()
                await route.fulfill(response=response)
                finished.set()
            else:
                await route.fulfill(response=response)
        await page.route('**/api/projects',projects)
        await page.route('**/api/collaboration**',lambda route:route.fulfill(
            json={'configured':False,'connected':False,'files':0,'revision':'test','author':'test'}))
        await page.route('**/charts/*/preview*',lambda route:route.fulfill(content_type='image/png',body=
            base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG9sAAAAASUVORK5CYII=')))
        try:
            await page.goto(url,wait_until='domcontentloaded')
            await asyncio.wait_for(started.wait(),10)
            await page.locator('#standardizeDialog').wait_for(state='visible')
            await page.locator('#workspaceRecent').select_option('foraging')
            await page.locator('#workspaceResume').click()
            await page.wait_for_function('!document.getElementById("standardizeDialog").open')
            assert await page.locator('#workspaceResultReasons details').count()==1
            await page.wait_for_function('state.project==="foraging" && state.detail!==null')
            assert await page.locator('.chartCard').count()==1
            release.set()
            await asyncio.wait_for(finished.wait(),10)
            await page.wait_for_function('document.getElementById("modelApiUrl").value!==""')
            assert await page.evaluate('state.project')=='foraging'
            assert not errors,errors
            print(json.dumps({'entered':'foraging','dialog_closed':True,'startup_race_preserved_selection':True,'errors':errors}))
        finally:
            release.set()
            await browser.close()


def main():
    with tempfile.TemporaryDirectory(prefix='workspace-entry-test-') as temporary:
        projects=Path(temporary)/'projects';projects.mkdir()
        for name in ('a_default','foraging'):
            project=projects/name
            (project/'charts').mkdir(parents=True);(project/'data').mkdir()
            (project/'charts/one.py').write_text('pass')
            prep.write_json(project/'project.json',{'name':name})
            prep.save_state(project,{'status':'ready','mode':'direct','figures':[{'figure_id':'one'}],
                'warnings':['another.py：Traceback\nModuleNotFoundError: missing_dependency'],
                'validation':{'state':'passed'}})
        with patch.object(server,'PROJECTS',projects),patch.object(server.Handler,'log_message',lambda *args:None):
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            threading.Thread(target=http.serve_forever,daemon=True).start()
            try:
                with patch.dict(os.environ,{'CHART_STUDIO_PORT':str(http.server_port)}):
                    asyncio.run(check(f'http://127.0.0.1:{http.server_port}/'))
            finally:http.shutdown();http.server_close()


if __name__=='__main__':
    main()
