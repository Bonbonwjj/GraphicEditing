"""Temporary isolated server for v0.2.1 browser validation."""
from pathlib import Path
import tempfile
import os
import subprocess
from unittest.mock import patch
import server
import model_config
from tests.test_model_config import FakeKeyring
from collaboration_sync import CollaborationSync

os.environ['CHART_STUDIO_PORT'] = '18765'
with tempfile.TemporaryDirectory(prefix='plot-v021-browser-',dir=Path(__file__).parent) as temp:
    root = Path(temp)
    projects = root / 'projects'
    projects.mkdir()
    import json
    project = projects/'demo'
    (project/'charts').mkdir(parents=True)
    (project/'data').mkdir()
    (project/'project.json').write_text(json.dumps({'name':'Interactive QA','charts':['one','two']}),encoding='utf-8')
    source = "import os\nimport matplotlib.pyplot as plt\nfig, (left,right)=plt.subplots(1,2,figsize=(10,4))\nleft.plot([0,1],[1,2],label='Original')\nleft.set(xlabel='Time',ylabel='Score',title='Left')\nleft.grid(True)\nleft.spines['left'].set_linewidth(2.5)\nleft.legend(loc='lower right')\nright.plot([0,1],[2,1])\nright.set(xlabel='Other time',ylabel='Other score',title='Right')\nfig.tight_layout()\nfig.savefig(os.environ['CHART_OUTPUT'])\n"
    for chart in ('one','two'):
        (project/'charts'/(chart+'.py')).write_text(source,encoding='utf-8')
    (project/'charts/stats.py').write_text("import os\nimport matplotlib.pyplot as plt\nfig, ax=plt.subplots(figsize=(7,5))\nax.errorbar(.8,2,yerr=.3,fmt='none',capsize=8)\nax.scatter([.8],[2],s=150)\nax.boxplot([[1,1.5,2,2.5,3]],positions=[2],patch_artist=True)\nax.set(xlabel='Group',ylabel='Value',xlim=(0,3))\nfig.savefig(os.environ['CHART_OUTPUT'],bbox_inches='tight')\n",encoding='utf-8')
    (project/'charts/violin.py').write_text("import os\nimport matplotlib.pyplot as plt\nfig,(left,right)=plt.subplots(1,2,figsize=(10,4))\nleft.violinplot([[1,2,3,4,5],[2,3,4,5,6]],showmeans=True,showmedians=True,quantiles=[[.25,.75],[.5]])\nleft.set(xlabel='Group',ylabel='Value',xlim=(.5,2.5),ylim=(0,7))\nright.bar([0,1],[3,4],yerr=.2,capsize=4)\nright.stem([2,3],[2,3])\nfig.tight_layout()\nfig.savefig(os.environ['CHART_OUTPUT'])\n",encoding='utf-8')
    (project/'charts/points.py').write_text("import os\nimport matplotlib.pyplot as plt\nfrom interactive_style import apply_interactive_style\nfig,(a,b)=plt.subplots(1,2,figsize=(10,5))\nvalues=[1,2,2,3,3,4,20]\na.boxplot([values],positions=[1],patch_artist=True,showmeans=True)\na.scatter([.94,.96,.98,1,1.02,1.04,1.06],values,c='purple',alpha=.5)\nb.violinplot([values],positions=[1],showmeans=True)\nb.scatter([.94,.96,.98,1,1.02,1.04,1.06],values,c='green',alpha=.5)\na.set(xlim=(.5,1.5),ylim=(0,22));b.set(xlim=(.5,1.5),ylim=(0,22))\napply_interactive_style(fig,{})\nfig.savefig(os.environ['CHART_OUTPUT'])\n",encoding='utf-8')
    (project/'charts/point_groups.py').write_text("import os\nimport matplotlib.pyplot as plt\nfig,(a,b)=plt.subplots(1,2,figsize=(10,5))\nvalues=[1,2,2,3,3,4,20]\nfor axis,kind in [(a,'box'),(b,'violin')]:\n if kind=='box': axis.boxplot([values,values],positions=[1,2],patch_artist=True)\n else: axis.violinplot([values,values],positions=[1,2])\n axis.scatter([.95]*7+[2.05]*7,values+values,c=['purple']*7+['orange']*7,alpha=.5)\n axis.set(xlim=(.5,2.5),ylim=(0,22));axis.set_xticks([1,2],['DIS','Others'])\nfig.savefig(os.environ['CHART_OUTPUT'])\n",encoding='utf-8')
    (project/'charts/connections.py').write_text("import os\nimport matplotlib.pyplot as plt\nfig,ax=plt.subplots(figsize=(10,6))\na=[1,2,3,4];b=[2,4,6,8]\nfor i,(left,right) in enumerate(zip(a,b)):\n ax.plot([1,2],[left,right],color='#bbbbbb',linewidth=.8,marker='o' if i==0 else 'None',markerfacecolor='#440088',markeredgecolor='#440088')\nfor left,right in zip(a,b):ax.plot([4,5],[left+10,right+10],color='#bbbbbb',linewidth=.8)\nfor x,values in [(1,a),(2,b),(4,[v+10 for v in a]),(5,[v+10 for v in b])]:ax.scatter([x]*4,values,color='#8844aa')\nax.boxplot([a,b,[v+10 for v in a],[v+10 for v in b]],positions=[1,2,4,5],patch_artist=True)\nax.plot([1,2],[2.5,5],color='black',marker='D',linewidth=2)\nax.plot([1,1,2,2],[9,9.5,9.5,9],color='black');ax.text(1.5,9.8,'***')\nax.set(xlim=(.5,5.5),ylim=(0,20))\nfig.savefig(os.environ['CHART_OUTPUT'])\n",encoding='utf-8')
    with patch.object(server, 'git' , lambda *args: subprocess.CompletedProcess(args,0)), patch.object(server, 'PROJECTS', projects), patch.object(server, 'SYNC', CollaborationSync(root)), patch.object(model_config, 'CONFIG_PATH', root/'settings.json'), patch.object(model_config, 'keyring', FakeKeyring()), patch.object(model_config, '_session_secret', None):
        server.LocalHTTPServer(('127.0.0.1', 18765), server.Handler).serve_forever()
