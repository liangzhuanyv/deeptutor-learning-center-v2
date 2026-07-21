"""Advisory recommendation center; it never mutates learning plans or mastery."""
from __future__ import annotations
import json, re, time
from typing import Any
from .normalization import canonical_json, clean_text
from .repository import LearningCenterNotFoundError, LearningCenterRepository, LearningCenterValidationError

RULE_PROVIDER='rules'; RULE_MODEL='recommendation-v1'; PROMPT_VERSION='recommendation-rules/v1'


def _loads(value: str | None, fallback: Any) -> Any:
    try: value=json.loads(value or '')
    except (TypeError,ValueError): return fallback
    return value if isinstance(value,type(fallback)) else fallback


class LearningRecommendationService:
    def __init__(self, repository: LearningCenterRepository | None=None) -> None: self.repository=repository or LearningCenterRepository()
    def _serialize(self, conn: Any, row: Any) -> dict[str,Any]:
        actions=[{**dict(a),'payload':_loads(a['payload_json'],{})} for a in conn.execute('SELECT * FROM ai_recommendation_actions WHERE recommendation_id=? ORDER BY created_at DESC',(row['id'],))]
        result={**dict(row),'evidence':_loads(row['evidence_json'],[]),'proposed_action':_loads(row['proposed_action_json'],{}),'actions':actions}
        result.pop('evidence_json',None); result.pop('proposed_action_json',None); return result
    def list(self, *, project_id: str | None=None, limit: int=50) -> list[dict[str,Any]]:
        with self.repository._connect() as conn:
            rows=conn.execute('SELECT * FROM ai_recommendations '+('WHERE project_id=? ' if project_id else '')+'ORDER BY created_at DESC LIMIT ?', ((project_id,) if project_id else ())+(max(1,min(limit,100)),)).fetchall()
            return [self._serialize(conn,row) for row in rows]
    def _create(self, conn: Any, *, project_id: str, kind: str, title: str, explanation: str, evidence: list[dict[str,Any]], action: dict[str,Any], confidence: float, minutes: int | None, now: float) -> None:
        fingerprint=canonical_json({'type':kind,'action':action,'evidence':evidence})
        # Repeated dashboard refreshes must not flood the feed with identical advice.
        for row in conn.execute('SELECT id,evidence_json,proposed_action_json FROM ai_recommendations WHERE project_id=? AND recommendation_type=? AND created_at>?',(project_id,kind,now-3600)):
            if canonical_json({'type':kind,'action':_loads(row['proposed_action_json'],{}),'evidence':_loads(row['evidence_json'],[])})==fingerprint: return
        conn.execute('INSERT INTO ai_recommendations (id,project_id,recommendation_type,title,explanation,evidence_json,proposed_action_json,provider,model,prompt_version,confidence,estimated_minutes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(self.repository._new_id('recommendation'),project_id,kind,title,explanation,canonical_json(evidence),canonical_json(action),RULE_PROVIDER,RULE_MODEL,PROMPT_VERSION,confidence,minutes,now,now))
    def generate(self, *, project_id: str, trigger: str='dashboard_open', time_budget_text: str='') -> list[dict[str,Any]]:
        if trigger not in {'dashboard_open','requested','practice_completion','mock_exam_completion','repeated_errors','manual_mastery_error','import_completion','time_budget'}: raise LearningCenterValidationError('Unsupported recommendation trigger')
        now=time.time()
        with self.repository._connect() as conn:
            self.repository._require_project(conn,project_id)
            due=conn.execute("SELECT q.id,q.stem,w.wrong_count FROM wrong_question_states w JOIN questions q ON q.id=w.question_id WHERE w.project_id=? AND w.state IN ('review_due','reviewing') ORDER BY w.last_wrong_at DESC LIMIT 10",(project_id,)).fetchall()
            reopen=conn.execute("SELECT q.id,q.stem,w.wrong_count FROM wrong_question_states w JOIN questions q ON q.id=w.question_id WHERE w.project_id=? AND w.state='reopen_suggested' ORDER BY w.last_wrong_at DESC LIMIT 5",(project_id,)).fetchall()
            repeated=conn.execute("SELECT q.id,q.stem,w.wrong_count FROM wrong_question_states w JOIN questions q ON q.id=w.question_id WHERE w.project_id=? AND w.wrong_count>=2 ORDER BY w.wrong_count DESC LIMIT 5",(project_id,)).fetchall()
            quality=conn.execute("SELECT id,issue_type,severity,details_json FROM quality_issues WHERE project_id=? AND status='open' ORDER BY severity DESC LIMIT 5",(project_id,)).fetchall()
            if due: self._create(conn,project_id=project_id,kind='review_proposal',title='优先复习到期错题',explanation=f'发现 {len(due)} 道待复习错题；建议先完成一组短复习。',evidence=[{'question_id':r['id'],'wrong_count':r['wrong_count']} for r in due],action={'type':'start_practice','filters':{'status':'review_due','limit':min(10,len(due))}},confidence=.92,minutes=min(20,max(5,len(due)*2)),now=now)
            if repeated: self._create(conn,project_id=project_id,kind='similar_question_suggestion',title='用相似题验证反复错误点',explanation='多次错误不应直接改变掌握状态；建议使用相似题检查理解。',evidence=[{'question_id':r['id'],'wrong_count':r['wrong_count']} for r in repeated],action={'type':'similar_questions','question_id':repeated[0]['id']},confidence=.84,minutes=10,now=now)
            if reopen: self._create(conn,project_id=project_id,kind='reopen_mastery_suggestion',title='已掌握题出现新错误',explanation='人工“已掌握”决定仍然保留；以下建议仅供你决定是否重新纳入复习。',evidence=[{'question_id':r['id'],'wrong_count':r['wrong_count']} for r in reopen],action={'type':'review_reopen','question_ids':[r['id'] for r in reopen]},confidence=.91,minutes=10,now=now)
            if quality: self._create(conn,project_id=project_id,kind='import_quality_review',title='导入题库存在待处理质量项',explanation='建议先复核导入质量问题；任何修订都需人工确认。',evidence=[dict(r) for r in quality],action={'type':'open_import_quality'},confidence=.78,minutes=8,now=now)
            budget=self.parse_time_budget(time_budget_text) if time_budget_text else None
            if budget:
                limit=max(3,min(30,budget*2)); self._create(conn,project_id=project_id,kind='practice_proposal',title=f'{budget} 分钟训练建议',explanation=f'根据“{clean_text(time_budget_text)}”生成建议题量；开始前仍需你确认。',evidence=[{'trigger':trigger,'minutes':budget}],action={'type':'start_practice','filters':{'limit':limit,'status':'review_due' if due else None},'requires_confirmation':True},confidence=.75,minutes=budget,now=now)
        return self.list(project_id=project_id)
    @staticmethod
    def parse_time_budget(text: str) -> int | None:
        match=re.search(r'(\d{1,3})\s*(?:分钟|分|min(?:ute)?s?)',clean_text(text).lower())
        if not match: return None
        return max(1,min(180,int(match.group(1))))
    def decide(self, *, recommendation_id: str, action: str, payload: dict[str,Any] | None=None) -> dict[str,Any]:
        if action not in {'accepted','edited_accepted','ignored','deferred','reduced'}: raise LearningCenterValidationError('Unsupported recommendation action')
        now=time.time()
        with self.repository._connect() as conn:
            row=conn.execute('SELECT * FROM ai_recommendations WHERE id=?',(recommendation_id,)).fetchone()
            if not row: raise LearningCenterNotFoundError('Recommendation not found')
            # Audit only: never mutate mastery/content here. The UI uses
            # next_action to navigate into practice with prefilled filters.
            conn.execute('INSERT INTO ai_recommendation_actions (id,recommendation_id,action,payload_json,created_at) VALUES (?,?,?,?,?)',(self.repository._new_id('recommendation_action'),recommendation_id,action,canonical_json(payload or {}),now))
            result=self._serialize(conn,row)
        result['decision'] = action
        proposed = result.get('proposed_action') or {}
        if action in {'accepted','edited_accepted','reduced'} and proposed.get('type') in {'start_practice','review_reopen','similar_questions'}:
            filters = dict(proposed.get('filters') or {})
            if payload:
                # edited_accepted / reduced may override limit etc.
                for key in ('limit','status','module_id','difficulty','mode'):
                    if key in payload and payload[key] is not None:
                        filters[key] = payload[key]
            if action == 'reduced' and 'limit' in filters:
                try:
                    filters['limit'] = max(3, int(filters['limit']) // 2)
                except (TypeError, ValueError):
                    pass
            query = {
                'project_id': result['project_id'],
                **{k: v for k, v in filters.items() if v is not None and v != ''},
            }
            if proposed.get('type') == 'similar_questions' and proposed.get('question_id'):
                query['seed_question_id'] = proposed['question_id']
                query.setdefault('status', 'wrong')
            result['next_action'] = {
                'type': 'open_practice',
                'href': '/space/learning-center/practice',
                'query': query,
                'label': '按此建议开始练习',
                'requires_confirmation': bool(proposed.get('requires_confirmation', True)),
            }
        else:
            result['next_action'] = None
        return result
