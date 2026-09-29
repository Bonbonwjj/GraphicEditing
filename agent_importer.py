"""Convert the bundled human-data reproducibility package to Chart Studio."""
import csv, json, re, shutil
from pathlib import Path

def safe_id(v):
    v=re.sub(r"[^A-Za-z0-9_-]+","_",v.strip()).strip("_")
    if not v: raise ValueError("Invalid project ID")
    return v

def import_package(root, source_relative, project_id, name=None):
    base=(root/"data").resolve(); source=(base/source_relative).resolve()
    if base not in source.parents or not source.is_dir(): raise ValueError("Source must be inside data/")
    csv_dir,code_dir=source/"csv",source/"code"
    required=csv_dir/"direct_panel_metadata.csv"; renderer_file=code_dir/"render_figures_from_csv.py"
    if not required.is_file() or not renderer_file.is_file(): raise ValueError("Expected code/render_figures_from_csv.py and direct panel CSVs")
    project_id=safe_id(project_id); target=root/"projects"/project_id
    if target.exists(): raise ValueError("Project already exists")
    for d in ("data","charts","history","lib"): (target/d).mkdir(parents=True)
    csv_files=sorted(csv_dir.glob("*.csv"))
    for p in csv_files: shutil.copy2(p,target/"data"/p.name)
    renderer=renderer_file.read_text(encoding="utf-8").replace("import textwrap","import os\nimport textwrap").replace('CSV = PACKAGE / "csv"','CSV = PACKAGE / "data"').replace('fig.savefig(OUT / f"heatmap_{heatmap_id}.png", dpi=300, bbox_inches="tight")','fig.savefig(os.environ["CHART_OUTPUT"], dpi=300, bbox_inches="tight")')
    (target/"lib"/"__init__.py").write_text("",encoding="utf-8")
    (target/"lib"/"source_renderer.py").write_text(renderer,encoding="utf-8")
    head=("import os\nfrom pathlib import Path\nimport matplotlib.pyplot as plt\nimport pandas as pd\nfrom studio_style import finish_figure\n"+f"from projects.{project_id}.lib import source_renderer as renderer\n\nproject=Path(os.environ['CHART_PROJECT_DIR'])\n")
    with required.open(encoding="utf-8-sig",newline="") as f: panels=list(csv.DictReader(f))
    charts=[]
    for p in panels:
        chart=safe_id(p["panel_id"]); charts.append(chart)
        src=head+"panels=pd.read_csv(project/'data/direct_panel_metadata.csv')\nvalues=pd.read_csv(project/'data/direct_panel_subject_values.csv')\n"+f"panel=panels[panels.panel_id.eq({p['panel_id']!r})].iloc[0]\n"+"fig,ax=plt.subplots(figsize=(5.4,4.8))\nrenderer.draw_panel(ax,panel,values[values.panel_id.eq(panel.panel_id)])\nax.set_position([.34,.23,.60,.66])\nfinish_figure(fig,os.environ['CHART_OUTPUT'])\n"
        (target/"charts"/(chart+".py")).write_text(src,encoding="utf-8")
    for pid,chart,size in [("03_obs_vs_nobs_score_relevance","score_relevance_timecourse",(5.4,4.8)),("05_obs_vs_disd_noticed_dimensions","noticed_dimensions_timecourse",(7.2,4.8))]:
        charts.append(chart); src=head+"values=pd.read_csv(project/'data/timecourse_subject_values.csv')\nmetadata=pd.read_csv(project/'data/timecourse_metadata.csv')\n"+f"fig,ax=plt.subplots(figsize={size!r})\nrenderer.draw_timecourse(ax,{pid!r},values,metadata)\nfig.tight_layout(pad=1.4)\nfinish_figure(fig,os.environ['CHART_OUTPUT'])\n"
        (target/"charts"/(chart+".py")).write_text(src,encoding="utf-8")
    for hm in ("baseline_corrected","no_baseline"):
        chart="heatmap_"+hm; charts.append(chart)
        (target/"charts"/(chart+".py")).write_text(head+f"metadata=pd.read_csv(project/'data/heatmap_metadata.csv')\nrenderer.draw_heatmap({hm!r},metadata)\n",encoding="utf-8")
    (target/"project.json").write_text(json.dumps({"name":name or project_id,"description":f"Agent imported {len(charts)} editable charts from {source_relative}."},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"project":project_id,"charts":charts,"files":len(csv_files)}
