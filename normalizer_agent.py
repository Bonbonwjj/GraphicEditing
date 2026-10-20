"""Local normalization agent. Start with `python normalizer_agent.py`."""
import ast
import json
import os
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent_http import JSONHandler
from model_config import validate_max_output_tokens, validate_url

ROOT = Path(__file__).resolve().parent
NORMALIZATION_SKILL = ROOT / "skills" / "chart-normalization" / "SKILL.md"
MODEL_PROMPT_CHAR_LIMIT = 80_000


def compact_model_data(items, budget=25_000):
    """Send whole CSV sample rows under a shared budget; retain schema and hashes."""
    result = []
    for item in items:
        entry = dict(item)
        lines = item.get('content', '').splitlines(keepends=True)
        if lines:
            content = lines[0]
            included = 0
            for row in lines[1:]:
                if len(content) + len(row) > min(12_000, budget):
                    break
                content += row
                included += 1
            entry['content'] = content
            if included < len(lines)-1:
                entry['content_scope'] = 'truncated_sample' if included else 'schema_only'
                entry['included_row_count'] = included
            budget -= len(content)
        result.append(entry)
    return result


def relevant_style_profile(source, profile):
    """Keep the full common policy and only plausible artist templates.

    Unknown or mixed chart types retain the complete profile. This reduces
    model input only; the Harness still renders against the full saved profile.
    """
    if not isinstance(profile, dict) or profile.get('id') != 'human-data-fixed-style':
        return profile, []
    methods = {node.func.attr for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    families = []
    if methods & {'imshow','pcolormesh','matshow'}:
        families.append('heatmap')
    if methods & {'violinplot','violin'}:
        families.append('two_group_violin')
    if methods & {'boxplot','bxp'}:
        families.append('two_group_box')
    if methods & {'bar','barh'}:
        families += ['two_group_bar','grouped_bar']
    if 'hist' in methods:
        families.append('histogram')
    if 'scatter' in methods:
        families.append('scatter')
    if 'errorbar' in methods:
        families += ['two_group_mean_sem','timecourse_mean_sem','line']
    if 'plot' in methods:
        families.append('line')
    families = list(dict.fromkeys(families))
    if not families:
        return profile, []
    selected = {name: spec for name,spec in profile.get('chart_types',{}).items() if name in families}
    return {**profile, 'chart_types': selected}, families


def check_source(source, style_profile=None):
    """Check structural plotting rules; visual values need Figure inspection later."""
    if not isinstance(source, str) or len(source) > 100_000:
        raise ValueError("Invalid Python source")
    tree = ast.parse(source)
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = {func.id for func in calls if isinstance(func, ast.Name)}
    attrs = {func.attr for func in calls if isinstance(func, ast.Attribute)}
    violations = []
    fixed_profile = isinstance(style_profile, dict) and style_profile.get("id") == "human-data-fixed-style"
    if fixed_profile:
        for call in ("apply_normalization_style", "finish_normalized_figure"):
            if call not in names:
                violations.append({"rule": call, "message": f"Missing {call}() call"})
    if "show" in attrs:
        violations.append({"rule": "no_show", "message": "Remove plt.show() from the final script"})
    if "CHART_PROJECT_DIR" not in source:
        violations.append({"rule": "project_path", "message": "Use CHART_PROJECT_DIR for data paths"})
    if "CHART_OUTPUT" not in source:
        violations.append({"rule": "output_path", "message": "Use CHART_OUTPUT for the figure"})
    return {"status": "pass" if not violations else "fail", "violations": violations,
            "visual_rules_verified": False,
            "note": "Static check only; visual values require running and inspecting the Figure."}


def materialize_normalization_result(result, source):
    """Apply model-supplied exact edits without trusting it to rewrite the whole file."""
    status = result.get('status')
    edits = result.get('edits')
    complete = result.get('normalized_source')
    if status != 'proposed':
        if edits:
            raise ValueError('规范化模型对非候选状态返回了代码修改；本轮未修改图片。')
        result['normalized_source'] = source
        return result
    if edits is not None:
        if complete is not None or not isinstance(edits, list) or not 1 <= len(edits) <= 30:
            raise ValueError('规范化模型返回的代码替换格式不正确；本轮未修改图片。')
        candidate = source
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError('规范化模型返回的代码替换格式不正确；本轮未修改图片。')
            old, new = edit.get('old'), edit.get('new')
            if (not isinstance(old, str) or not old or not isinstance(new, str) or
                    len(old) > 20_000 or len(new) > 20_000 or candidate.count(old) != 1):
                raise ValueError('规范化模型的代码替换无法在原图脚本中唯一定位；本轮未修改图片。')
            candidate = candidate.replace(old, new, 1)
        result['normalized_source'] = candidate
    elif not isinstance(complete, str):
        fields=', '.join(sorted(result))[:200]
        raise ValueError(f'规范化模型声明要修改，却没有返回 edits 或 normalized_source（实际字段：{fields}）；本轮未修改图片。')
    return result


def local_legacy_line_normalization(source, data_schema, style_profile):
    """Migrate a narrowly recognized one-axis legacy line plot without an LLM.

    All other plots, including uncertainty-bearing plots, keep the full Agent path.
    The Harness still renders and validates this candidate before showing it.
    """
    profile = (style_profile.get('chart_types') or {}).get('line') or {}
    width = profile.get('line_width_pt')
    if not isinstance(width, (int, float)) or width <= 0:
        return None
    required = ('from studio_style import apply_style, finish_figure', 'apply_style()',
                'finish_figure(fig, os.environ["CHART_OUTPUT"])', 'fig.show()')
    if any(source.count(item) != 1 for item in required):
        return None
    if any(key in source for key in ('apply_normalization_style', 'finish_normalized_figure')):
        return None
    uncertainty = ('sem', 'std', 'stderr', 'error', 'ci_', '_ci', 'lower', 'upper', 'sd_','_sd')
    for item in data_schema:
        for column in item.get('columns', []):
            name = str(column).lower()
            if any(token in name for token in uncertainty):
                return None
    tree = ast.parse(source)
    allowed_imports = {'csv','os','pathlib','matplotlib.pyplot','studio_style'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name not in allowed_imports for alias in node.names):
            return None
        if isinstance(node, ast.ImportFrom) and node.module not in allowed_imports:
            return None
        if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            return None
    plot_calls = []
    subplot_calls = 0
    allowed_ax = {'plot','set','legend','set_xlabel','set_ylabel','set_title','set_xlim','set_ylim',
                  'set_xticks','set_yticks','tick_params'}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == 'ax':
            if node.func.attr not in allowed_ax:
                return None
            if node.func.attr == 'plot':
                plot_calls.append(node)
        if isinstance(owner, ast.Name) and owner.id == 'plt' and node.func.attr == 'subplots':
            subplot_calls += 1
        elif isinstance(owner, ast.Name) and owner.id == 'plt':
            return None
        if isinstance(owner, ast.Name) and owner.id == 'fig' and node.func.attr != 'show':
            return None
        if node.func.attr in {'twinx','twiny','add_subplot','subplot','figure','errorbar','scatter',
                              'bar','barh','hist','imshow','pcolormesh','fill_between','axhline','axvline'}:
            return None
    if subplot_calls != 1 or not plot_calls:
        return None
    widths = []
    for call in plot_calls:
        keyword = next((item for item in call.keywords if item.arg in ('linewidth','lw')),None)
        if keyword is None or not isinstance(keyword.value, ast.Constant) or not isinstance(keyword.value.value,(int,float)):
            return None
        widths.append(float(keyword.value.value))
    if len(set(widths)) != 1:
        return None
    candidate = source.replace(required[0], 'from studio_style import apply_normalization_style, finish_normalized_figure')
    candidate = candidate.replace(required[1], 'apply_normalization_style()')
    candidate = candidate.replace(required[2],
                                  'for _normalized_line in ax.get_lines():\n'
                                  f'    _normalized_line.set_linewidth({width!r})\n'
                                  'finish_normalized_figure(fig, os.environ["CHART_OUTPUT"], chart_type="line")')
    candidate = candidate.replace('fig.show()\n','')
    if 'fig.show()' in candidate:
        return None
    ast.parse(candidate)
    return {'status':'proposed','message':'已按固定折线图模板调整单图入口；CSV 未提供误差含义或误差列，因此没有添加误差线。',
            'changes':['使用固定字体、画布、坐标轴和图例规范','统一已有折线的线宽','移除图上标题与交互式 show 调用'],
            'warnings':['未添加误差线：已上传的绘图 CSV 没有明确的误差值及其统计含义。'],
            'unsupported':[],'normalized_source':candidate,'method':'local_legacy_line',
            'check':check_source(candidate,style_profile)}


def normalize_source(source, data_schema, style_profile, related_sources=None, skill_text=None, model_auth=None):
    if not isinstance(source, str) or not source.strip() or len(source) > 100_000:
        raise ValueError("Invalid Python source")
    ast.parse(source)
    fixed_profile = isinstance(style_profile, dict) and style_profile.get("id") == "human-data-fixed-style"
    if not isinstance(skill_text, str) or not skill_text.strip() or len(skill_text) > 100_000:
        raise ValueError("Missing or invalid normalization Skill")
    if fixed_profile and skill_text == NORMALIZATION_SKILL.read_text(encoding='utf-8'):
        local = local_legacy_line_normalization(source,data_schema,style_profile)
        if local is not None:
            return local
    model_auth = model_auth or {}
    key = model_auth.get('api_key') or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError('尚未配置模型 API 密钥；请点击页面顶部的「API 配置」保存密钥。')
    url = validate_url(model_auth.get('api_url') or os.environ.get("LLM_API_URL", "https://api.siliconflow.cn/v1/chat/completions"))
    model_profile, template_candidates = relevant_style_profile(source, style_profile)
    instruction = ("You normalize one Matplotlib chart script for the local Chart Studio. "
                   "Return only one JSON object with status, message, changes, warnings, unsupported. "
                   "status is proposed, already_compliant, needs_clarification, or unsupported. "
                   "For proposed, prefer edits: a short list of exact {old,new} string replacements applied sequentially to the original source. Each old must occur exactly once at its step. Use normalized_source only when exact replacements cannot represent the change. Never return both. "
                   "For all other statuses, omit code and edits; the original source is retained. "
                   "Preserve the chart type, existing artists, data loading, filtering, calculations, plotted x/y values and scientific meaning. The selected Skill may add only data-supported line error bars under its explicit rules; report missing error data while still rendering the chart. Never add a scatter fit when the source has no model. "
                   "Apply only the selected Skill, supplied normalization profile and relevant visual rules. Do not use the old 8 pt demo style. "
                   "If a rule cannot safely apply, return needs_clarification or list it in unsupported; never invent p values or change statistical methods. "
                   "Use CHART_PROJECT_DIR and CHART_OUTPUT for reproducible rendering, and keep the script runnable. "
                   + ("Import apply_normalization_style and finish_normalized_figure from studio_style. Call apply_normalization_style() before creating the figure and finish_normalized_figure(fig, CHART_OUTPUT, chart_type=...) to export it. Choose chart_type only for a truly matching profile template; otherwise pass None. " if fixed_profile else "Preserve valid plotting helpers unless the selected Skill explicitly requires a change. ")
                   + "Related shared sources are read-only context. If the required style is controlled there and cannot be changed safely in the entry script, return unsupported and explain the needed shared-file edit. "
                   "CSV content may be a bounded sample and omitted_read_only_paths may list helpers excluded from the model prompt. Do not infer omitted values or helper behavior; report rules that need the missing evidence. "
                   "Do not add network, shell, secret, or unrelated file access. "
                   "Describe every change. Do not claim that code was run.\n\n"
                   + skill_text + "\n\n"
                   "FINAL JSON CONTRACT: proposed MUST include either edits:[{old:string,new:string},...] or normalized_source:string. "
                   "Descriptions in changes do not count as code. If no code change can be supplied, use needs_clarification or unsupported, not proposed. "
                   "Do not omit status, message, changes, warnings, unsupported. Return the JSON object only.\n")
    related = related_sources or {}
    selected_related = {}
    omitted_related = []
    related_budget = 22_000
    for path, content in related.items():
        if len(content) <= related_budget:
            selected_related[path] = content
            related_budget -= len(content)
        else:
            omitted_related.append(path)
    user_content = {"source": source, "data_schema": compact_model_data(data_schema),
                    "related_sources": selected_related,
                    "omitted_read_only_paths": omitted_related,
                    "style_profile": model_profile,
                    "template_candidates": template_candidates}
    serialized = json.dumps(user_content, ensure_ascii=False)
    if len(instruction) + len(serialized) > MODEL_PROMPT_CHAR_LIMIT:
        user_content['data_schema'] = compact_model_data(data_schema, budget=0)
        serialized = json.dumps(user_content, ensure_ascii=False)
    if len(instruction) + len(serialized) > MODEL_PROMPT_CHAR_LIMIT:
        raise ValueError('规范化所需代码和规则超过轻量模型输入预算；请缩小单图绘图入口或共用依赖。')
    model_name = model_auth.get('model') or os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-4B")
    configured_limit = validate_max_output_tokens(model_auth.get('max_output_tokens', 16384))
    task_limit = max(8192, min(32768, len(source) // 3 + 4096))
    output_limit = min(configured_limit, task_limit, 16384 if model_name.lower() == 'deepseek-v4.1-flash' else 65536)
    payload = {"model": model_name,
               "messages": [{"role": "system", "content": instruction},
                            {"role": "user", "content": serialized}],
               "temperature": 0.1,
               "max_tokens": output_limit}
    if model_name.lower() in ('glm-5.3-flash-nvfp4','glm-5.3-flash','glm-5.3'):
        payload['reasoning_effort'] = 'low'
    prompt_chars = sum(len(item['content']) for item in payload['messages'])
    print(f"Normalization model request: prompt_chars={prompt_chars}, source_chars={len(source)}, "
          f"templates={','.join(template_candidates) or 'all'}, max_tokens={payload['max_tokens']}", flush=True)
    started = time.monotonic()
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"}, method="POST")
    from model_connection import report_result
    connection={'api_url':url,'model':model_name,'api_key':key}
    outcome = 'incomplete'
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            completion = json.load(response)
            choice = completion["choices"][0]
            report_result(connection,True)
            if choice.get('finish_reason') == 'length':
                usage = completion.get('usage') or {}
                details = usage.get('completion_tokens_details') or {}
                reasoning_tokens = details.get('reasoning_tokens') if isinstance(details,dict) else None
                if isinstance(reasoning_tokens,int) and reasoning_tokens >= payload['max_tokens']*.9:
                    raise ValueError('规范化模型的推理耗尽输出预算；本轮未生成完整代码。已请求低推理强度，若重试仍如此，请检查服务端是否透传 reasoning_effort。')
                raise ValueError('规范化模型输出达到长度上限，未得到完整代码；请缩小本轮处理的绘图脚本。')
            message = choice.get('message', {}).get('content')
            usage = completion.get('usage') or {}
            details = usage.get('completion_tokens_details') or {}
            reasoning_tokens = details.get('reasoning_tokens') if isinstance(details, dict) else None
            print(f"Normalization model response: finish_reason={choice.get('finish_reason')}, "
                  f"completion_tokens={usage.get('completion_tokens')}, reasoning_tokens={reasoning_tokens}, "
                  f"content_chars={len(message) if isinstance(message, str) else 0}", flush=True)
            if not isinstance(message, str) or not message.strip():
                consumed = usage.get('completion_tokens')
                usage_note = (f'（输出 {consumed} token，其中推理 {reasoning_tokens} token）'
                              if isinstance(consumed, int) and isinstance(reasoning_tokens, int) else '')
                raise ValueError('规范化模型返回了空的最终内容' + usage_note +
                                 '；未获得 JSON 或候选代码。模型可能把预算用于推理，或服务端没有返回最终答案。')
        outcome = 'response'
    except TimeoutError as error:
        report_result(connection,False,'规范化模型接口连接或读取超时')
        outcome = 'timeout'
        elapsed = round(time.monotonic() - started, 1)
        raise ValueError(f'规范化模型接口连接或读取超时（已等待 {elapsed} 秒）；本轮未生成候选图。'
                         '这一步尚未进入绘图渲染，请检查模型服务排队、负载或网络连接。') from error
    except urllib.error.HTTPError as error:
        report_result(connection,False,'规范化模型请求失败：HTTP '+str(error.code))
        outcome = 'http_' + str(error.code)
        if error.code == 429:
            retry_after = error.headers.get('Retry-After', '').strip()
            try:
                payload = json.loads(error.read(4096).decode('utf-8', errors='replace'))
            except (ValueError, OSError):
                payload = {}
            detail = payload.get('error', payload.get('message', payload.get('detail', ''))) if isinstance(payload, dict) else ''
            if isinstance(detail, dict):
                detail = detail.get('message', detail.get('detail', ''))
            detail = ' '.join(str(detail).split())[:240] if isinstance(detail, str) else ''
            explanation = '规范化模型服务返回 429：请求频率、并发数或额度受限；本轮未生成候选图。'
            if detail:
                explanation += ' 服务端说明：' + detail
            if retry_after.isdigit():
                explanation += ' 建议等待 ' + retry_after + ' 秒后重试。'
            raise ValueError(explanation) from error
        raise ValueError('规范化模型请求失败：HTTP ' + str(error.code)) from error
    except urllib.error.URLError as error:
        report_result(connection,False,'规范化模型连接不可用')
        outcome = 'network_error'
        if isinstance(getattr(error, 'reason', None), TimeoutError):
            elapsed = round(time.monotonic() - started, 1)
            raise ValueError(f'规范化模型接口连接或读取超时（已等待 {elapsed} 秒）；本轮未生成候选图。'
                             '这一步尚未进入绘图渲染，请检查模型服务排队、负载或网络连接。') from error
        raise ValueError("规范化模型连接失败：" + str(getattr(error,'reason','连接不可用'))) from error
    finally:
        print(f"Normalization model result: outcome={outcome}, elapsed_seconds={time.monotonic()-started:.1f}", flush=True)
    answer = message.strip()
    if answer.startswith('<think>') and '</think>' in answer:
        answer = answer.split('</think>', 1)[1].strip()
    if answer.startswith('```'):
        first_line, _, fenced = answer.partition('\n')
        if first_line.strip().lower() in ('```', '```json') and fenced.rstrip().endswith('```'):
            answer = fenced.rstrip()[:-3].strip()
    try:
        result = json.loads(answer)
    except json.JSONDecodeError as error:
        prefix = answer[:100].replace('\n', ' ').replace('\r', ' ')
        raise ValueError(f'规范化模型返回了非 JSON 内容（开头：{prefix!r}）；本轮未修改图片。请检查模型是否支持按要求输出完整 JSON。') from error
    if not isinstance(result, dict) or result.get("status") not in (
            "proposed", "already_compliant", "needs_clarification", "unsupported"):
        raise ValueError("Normalization model returned an invalid status")
    result = materialize_normalization_result(result, source)
    candidate = result.get("normalized_source")
    if not isinstance(candidate, str) or len(candidate) > 100_000:
        raise ValueError("Normalization model returned invalid source")
    ast.parse(candidate)
    if not isinstance(result.get("message"), str) or not result["message"].strip():
        raise ValueError("Normalization model did not explain its result")
    if not isinstance(result.get("changes"), list) or not isinstance(result.get("warnings"), list):
        raise ValueError("Normalization model returned invalid change information")
    if result["status"] == "proposed" and candidate == source:
        result["status"] = "already_compliant"
    result["check"] = check_source(candidate, style_profile)
    if result["status"] == "already_compliant" and result["check"]["status"] != "pass":
        result["status"] = "needs_clarification"
        result["message"] = "The chart has not yet adopted the fixed normalization entry points."
    return result


class Handler(JSONHandler):
    max_body = 12_000_000
    def route(self, body):
        source = body.get("source")
        if self.path == "/v1/check":
            result = check_source(source, body.get("style_profile"))
            result["request_id"] = body.get("request_id")
            result["base_revision"] = body.get("base_revision")
            return result
        if self.path == "/v1/normalize":
            result = normalize_source(source, body.get("data_schema", []), body.get("style_profile", {}),
                                      body.get("related_sources", {}), body.get("skill_text"), body.get('model_auth'))
            result["request_id"] = body.get("request_id")
            result["base_revision"] = body.get("base_revision")
            return result
        raise ValueError("Route not found")


if __name__ == "__main__":
    port = int(os.environ.get("NORMALIZER_AGENT_PORT", "8766"))
    print(f"Normalization agent: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
