"""Optional real-browser smoke test using temporary projects and fake auth.

Requires playwright (development only) and a local Chrome/Chromium executable.
No user configuration, real credentials, model calls, or remote Git operations.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import model_config
from collaboration_sync import CollaborationSync
from tests.test_model_config import FakeKeyring
from playwright.sync_api import sync_playwright


def assert_select_contrast(page, selector):
    contrast = page.locator(selector).evaluate('''node => {
        const luminance = color => {
            const rgb = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => {
                v /= 255;
                return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
            });
            return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
        };
        return [node, ...node.options].map(element => {
            const style = getComputedStyle(element);
            const a = luminance(style.color), b = luminance(style.backgroundColor);
            return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        });
    }''')
    assert min(contrast) >= 4.5, (selector, contrast)


def main():
    with ExitStack() as stack:
        root=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='plot-ui-test-')))
        projects=root/'projects';projects.mkdir()
        source=root/'source';source.mkdir();(source/'analysis.py').write_text('raise RuntimeError("must not execute")\n')
        (source/'data.csv').write_text('x,y\n1,2\n')
        (source/'small').mkdir();(source/'small/plot.py').write_text('# independent small scope\n')
        (source/'large').mkdir();(source/'large/other.py').write_text('#'+'x'*190000+'\n')
        stack.enter_context(patch.object(server,'PROJECTS',projects))
        stack.enter_context(patch.object(server,'SYNC',CollaborationSync(root)))
        stack.enter_context(patch.object(model_config,'CONFIG_PATH',root/'.model-api.json'))
        stack.enter_context(patch.object(model_config,'keyring',FakeKeyring()))
        stack.enter_context(patch.object(model_config,'_session_secret',None))
        stack.enter_context(patch.dict(os.environ,{'OPENAI_API_KEY':'','LLM_API_KEY':''}))
        stack.enter_context(patch.object(server.Handler,'log_message',lambda *args:None))
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        stack.callback(http.server_close);stack.callback(http.shutdown)
        stack.enter_context(patch.dict(os.environ,{'CHART_STUDIO_PORT':str(http.server_port)}))
        threading.Thread(target=http.serve_forever,daemon=True).start()
        screenshots=Path(tempfile.mkdtemp(prefix='plot-ui-screenshots-'))
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('PLOT_TEST_CHROME','/opt/google/chrome/chrome'),headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1080})
            errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
            page.route('**/api/collaboration**',lambda route:route.fulfill(json={'configured':False,'connected':False,'remote':'','branch':'','files':0,'revision':'test','author':'test','local_changes':0}))
            status={'connected':False,'sharing':False,'storage':'session','pending':False,'message':'Test session only'}
            page.route('**/api/chatgpt/status',lambda route:route.fulfill(json=status))
            page.goto(f'http://127.0.0.1:{http.server_port}/')
            page.locator('#standardizeDialog').wait_for(state='visible')
            page.locator('#workspaceMode').select_option('new')
            page.locator('#projectSourcePath').fill(str(source))
            page.locator('#workspaceInspect').click()
            page.wait_for_function('document.getElementById("workspaceInventory").textContent.includes("analysis.py")')
            page.locator('#standardizeProjectName').fill('my_research')
            page.locator('#startStandardize').click()
            page.wait_for_function('document.getElementById("workspacePreparationState").textContent.includes("待分析")')
            assert page.locator('#workspaceEnter').is_disabled()
            assert not page.locator('#workspaceConsent').is_checked()
            page.locator('#workspaceAdvanced > summary').click()
            page.wait_for_function('document.getElementById("workspaceAnalysisSummary").textContent.includes("超出上限")')
            page.locator('#workspaceBatchPlan').click()
            page.wait_for_function('document.getElementById("workspaceBatchSummary").textContent.includes("覆盖 3 个源码文件")')
            assert not page.locator('#workspaceBatchConsent').is_checked()
            assert page.locator('#workspaceBatchStart').is_disabled()
            assert '超限' in page.locator('#workspaceBatchDetails').text_content()
            page.locator('#workspaceBatchConsent').check()
            assert page.locator('#workspaceBatchStart').is_enabled()
            # Planning alone is local; do not start real model work in this UI test.
            page.locator('#workspaceBatchConsent').uncheck()
            page.locator('#workspaceConsent').check()
            assert page.locator('#workspaceAnalyze').is_disabled()
            page.locator('#workspaceAnalysisScope').select_option('small')
            page.wait_for_function('document.getElementById("workspaceAnalysisSummary").textContent.includes("可提交分析")')
            assert not page.locator('#workspaceConsent').is_checked()
            assert page.locator('#workspaceAnalyze').is_disabled()
            page.locator('#workspaceConsent').check()
            assert page.locator('#workspaceAnalyze').is_enabled()
            page.locator('#workspaceRenameName').fill('Renamed research')
            page.locator('#workspaceRename').click()
            page.wait_for_function('document.getElementById("workspaceProjectTitle").textContent.includes("Renamed research")')
            page.wait_for_function('document.getElementById("workspaceRecent").selectedOptions[0].textContent.includes("Renamed research")')
            assert page.locator('#workspaceRecent').input_value()=='my_research'
            assert (projects/'my_research').is_dir()
            page.locator('#standardizeProjectName').fill('a_new_copy')
            assert page.locator('#workspacePreparation').is_hidden()
            assert '尚未更新已有工程' in page.locator('#workspaceMessage').inner_text()
            page.locator('#workspaceResume').click()
            page.locator('#workspacePreparation').wait_for(state='visible')
            assert 'Renamed research' in page.locator('#workspaceProjectTitle').inner_text()
            page.screenshot(path=str(screenshots/'project-prepare.png'))
            # Refresh must reopen the saved preparation state, without model work.
            page.reload();page.locator('#standardizeDialog').wait_for(state='visible')
            page.locator('#workspaceMode').select_option('new')
            page.wait_for_function('document.querySelector("#workspaceRecent option[value=my_research]") !== null')
            page.locator('#workspaceRecent').select_option('my_research');page.locator('#workspaceResume').click()
            page.wait_for_function('document.getElementById("workspacePreparationState").textContent.includes("待分析")')
            page.locator('#closeStandardize').click()
            page.locator('#modelConfigButton').click()
            page.locator('#modelProvider').select_option('api')
            page.locator('#apiEndpointPreset').select_option('siliconflow')
            assert page.locator('#modelApiUrl').input_value() == 'https://api.siliconflow.cn/v1/chat/completions'
            assert page.locator('#modelName').input_value() == ''
            assert page.locator('#testModelConfig').is_disabled()
            page.locator('#modelApiKey').fill('fake-unsaved-key')
            page.locator('#apiEndpointPreset').select_option('local')
            assert page.locator('#modelApiKey').input_value() == ''
            assert page.locator('#modelName').input_value() == 'glm-5.3'
            page.locator('#modelApiUrl').fill('https://custom.example.test/v1/chat/completions')
            assert page.locator('#apiEndpointPreset').input_value() == 'custom'
            assert 'custom.example.test' in page.locator('#apiDestinationNotice').inner_text()
            assert_select_contrast(page, '#apiEndpointPreset')
            page.locator('#modelProvider').select_option('chatgpt')
            page.locator('#chatgptSettings').wait_for(state='visible')
            assert not page.locator('#chatgptCodeConsent').is_checked()
            assert page.locator('#apiProviderFields').is_hidden()
            assert not page.locator('#modelApiUrl').evaluate('(node)=>node.required')
            status.update(connected=True,sharing=True,account_label='t***@example.test')
            page.route('**/api/chatgpt/models',lambda route:route.fulfill(json={'models':[{'id':'model-test','name':'Test Model'}]}))
            # Trigger status refresh without a live OAuth browser login.
            page.locator('#modelProvider').select_option('api');page.locator('#modelProvider').select_option('chatgpt')
            page.wait_for_function('!document.getElementById("chatgptLoadModels").disabled')
            page.locator('#chatgptLoadModels').click()
            page.wait_for_function('document.getElementById("chatgptModelSelect").value==="model-test"')
            for theme in ('light', 'dark'):
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for selector in ('#modelProvider', '#chatgptModelSelect', '#workspaceRecent', '#workspaceAnalysisScope'):
                    assert_select_contrast(page, selector)
                page.locator('#modelProvider').focus()
                assert page.locator('#modelProvider').evaluate('(node) => getComputedStyle(node).outlineStyle') != 'none'
                page.locator('#chatgptModelSelect').evaluate('(node) => node.disabled = true')
                assert page.locator('#chatgptModelSelect').is_disabled()
                page.locator('#chatgptModelSelect').evaluate('(node) => node.disabled = false')
                page.screenshot(path=str(screenshots/f'chatgpt-settings-{theme}.png'))
            page.screenshot(path=str(screenshots/'chatgpt-settings.png'))
            page.locator('#saveModelConfig').click()
            page.wait_for_function('document.getElementById("modelConfigState").textContent.includes("已保存")')
            saved=json.loads(model_config.CONFIG_PATH.read_text())
            assert saved['provider']=='chatgpt' and saved['allow_code_upload'] is False
            assert not any('token' in k for k in saved)
            # Delete the disposable working copy only, with explicit scope and
            # typed confirmation. Cancellation must never mutate the project.
            page.locator('#closeModelConfig').click()
            page.locator('#openWorkspace').click()
            page.locator('#workspaceRecent').select_option('my_research')
            page.locator('#workspaceDelete').click()
            page.locator('#workspaceDeletePanel').wait_for(state='visible')
            assert str(source) in page.locator('#workspaceDeleteScope').inner_text()
            assert str(projects/'my_research') in page.locator('#workspaceDeleteScope').inner_text()
            assert page.locator('#workspaceDeleteConfirm').is_disabled()
            page.locator('#workspaceDeleteName').fill('wrong-project')
            assert page.locator('#workspaceDeleteConfirm').is_disabled()
            page.locator('#workspaceDeleteCancel').click()
            assert (projects/'my_research/project.json').is_file()
            page.locator('#workspaceDelete').click()
            page.locator('#workspaceDeletePanel').wait_for(state='visible')
            page.locator('#workspaceDeleteName').fill('my_research')
            page.locator('#workspaceDeleteConfirm').click()
            page.wait_for_function('document.getElementById("workspaceMessage").textContent.includes("已删除 my_research")')
            assert not (projects/'my_research').exists()
            assert (source/'analysis.py').read_text()=='raise RuntimeError("must not execute")\n'
            assert (source/'data.csv').read_text()=='x,y\n1,2\n'
            assert page.locator('#workspaceRecent option').count()==1
            assert page.locator('#workspaceDelete').is_disabled()
            assert page.evaluate('state.project===null && state.chart===null && state.selectedCharts.size===0')
            assert page.locator('#sendChat').is_disabled()
            page.reload();page.locator('#standardizeDialog').wait_for(state='visible')
            page.wait_for_function('document.getElementById("status").textContent.includes("项目目录")')
            assert page.locator('#workspaceRecent option').count()==1
            browser.close()
            assert not errors, errors
        print('PASS: real Chrome import/resume, rename, scoped analysis/consent, model settings, deletion/source preservation; zero JS errors.')
        print('Screenshots:',screenshots)


if __name__=='__main__':main()
