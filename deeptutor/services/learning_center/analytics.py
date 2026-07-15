"""Read-only analytics projections for Learning Center v2."""
from __future__ import annotations
from typing import Any
from .repository import LearningCenterRepository
class LearningAnalyticsService:
 def __init__(self,repository:LearningCenterRepository|None=None): self.repository=repository or LearningCenterRepository()
 def _scope(self,project_id:str|None): return (' WHERE q.project_id=?',(project_id,)) if project_id else ('',())
 def knowledge_heatmap(self,project_id:str|None=None)->list[dict[str,Any]]:
  w,p=self._scope(project_id)
  with self.repository._connect() as c:
   return [dict(r) for r in c.execute('SELECT kp.id,kp.name,kp.project_id,COUNT(DISTINCT q.id) question_count,COUNT(a.id) attempt_count,SUM(CASE WHEN a.is_correct=0 THEN 1 ELSE 0 END) wrong_count FROM knowledge_points kp JOIN question_knowledge_points qkp ON qkp.knowledge_point_id=kp.id JOIN questions q ON q.id=qkp.question_id LEFT JOIN attempts a ON a.question_id=q.id'+(' WHERE kp.project_id=?' if project_id else '')+' GROUP BY kp.id ORDER BY wrong_count DESC,attempt_count DESC',p).fetchall()]
 def confidence(self,project_id:str|None=None)->list[dict[str,Any]]:
  with self.repository._connect() as c:
   rows=c.execute('SELECT a.confidence,COUNT(*) attempt_count,SUM(CASE WHEN a.is_correct=1 THEN 1 ELSE 0 END) correct_count FROM attempts a JOIN questions q ON q.id=a.question_id'+(' WHERE q.project_id=?' if project_id else '')+' GROUP BY a.confidence',(project_id,) if project_id else ()).fetchall()
   return [{**dict(r),'accuracy':r['correct_count']/r['attempt_count'] if r['attempt_count'] else None} for r in rows]
 def response_time(self,project_id:str|None=None)->list[dict[str,Any]]:
  with self.repository._connect() as c:return [dict(r) for r in c.execute('SELECT q.question_type,COUNT(*) attempt_count,AVG(a.elapsed_seconds) average_seconds,MIN(a.elapsed_seconds) min_seconds,MAX(a.elapsed_seconds) max_seconds FROM attempts a JOIN questions q ON q.id=a.question_id WHERE a.elapsed_seconds IS NOT NULL'+(' AND q.project_id=?' if project_id else '')+' GROUP BY q.question_type',(project_id,) if project_id else ()).fetchall()]
 def error_reasons(self,project_id:str|None=None)->list[dict[str,Any]]:
  with self.repository._connect() as c:
   rows=c.execute("SELECT CASE WHEN a.confidence='sure' THEN 'confident_error' WHEN a.confidence IN ('uncertain','guess') THEN 'uncertain_error' ELSE 'unmarked_error' END reason,COUNT(*) count FROM attempts a JOIN questions q ON q.id=a.question_id WHERE a.is_correct=0"+(' AND q.project_id=?' if project_id else '')+' GROUP BY reason',(project_id,) if project_id else ()).fetchall(); return [dict(r) for r in rows]
 def content_mix(self,project_id:str|None=None)->dict[str,int]:
  with self.repository._connect() as c:
   where='WHERE q.project_id=?' if project_id else ''; ps=(project_id,) if project_id else ()
   row=c.execute('SELECT COUNT(*) total,SUM(CASE WHEN NOT EXISTS(SELECT 1 FROM attempts a WHERE a.question_id=q.id) THEN 1 ELSE 0 END) new_count,SUM(CASE WHEN EXISTS(SELECT 1 FROM wrong_question_states w WHERE w.question_id=q.id AND w.wrong_count>0) THEN 1 ELSE 0 END) wrong_count,SUM(CASE WHEN EXISTS(SELECT 1 FROM review_schedule r WHERE r.question_id=q.id AND r.state=\'due\') THEN 1 ELSE 0 END) review_count FROM questions q '+where,ps).fetchone(); return {k:int(row[k] or 0) for k in row.keys()}
