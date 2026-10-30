"""Background import jobs with observable, bounded status messages."""
import threading
import time
import uuid


class ImportJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}
        self.active = set()

    def start(self, project, operation):
        with self.lock:
            if project in self.active:
                raise ValueError('此项目已有拆分任务，请等待完成。')
            ident = uuid.uuid4().hex
            self.active.add(project)
            self.jobs[ident] = dict(id=ident, project=project, status='working', stage='queued',
                                    message='任务已接收，等待开始处理。', started_at=time.time(),
                                    completed=0, total=0)

        def update(**fields):
            with self.lock:
                self.jobs[ident].update(fields, updated_at=time.time())

        def run():
            try:
                result = operation(update)
                update(status='completed', stage='completed', message='拆分完成，正在更新图集。',
                       result=result, finished_at=time.time())
            except Exception as exc:
                update(status='failed', stage='failed', message=str(exc), finished_at=time.time())
            finally:
                with self.lock:
                    self.active.discard(project)

        threading.Thread(target=run, daemon=True, name='plot-import-'+ident[:8]).start()
        return self.get(ident)

    def get(self, ident):
        with self.lock:
            if ident not in self.jobs:
                raise ValueError('拆分任务不存在或后台已重启；请先检查项目结果，避免重复导入。')
            return dict(self.jobs[ident])


JOBS = ImportJobs()
