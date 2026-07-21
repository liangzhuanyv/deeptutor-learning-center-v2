from pathlib import Path
from deeptutor.services.learning_center import LearningCenterRepository
from deeptutor.services.learning_center.recommendations import LearningRecommendationService

def test_recommendations_are_advisory_and_actions_are_audited(tmp_path: Path):
 r=LearningCenterRepository(tmp_path/'l.db'); p=r.create_project(name='P',kind='course'); s=r.create_content_source(project_id=p['id'],source_type='fixture'); b=r.create_bank(project_id=p['id'],source_id=s['id'],name='B'); v=r.create_bank_version(bank_id=b['id'],source_id=s['id'],version='v1'); q=r.create_question(project_id=p['id'],bank_id=b['id'],bank_version_id=v['id'],source_id=s['id'],stem='Q',source_answer='A')
 with r._connect() as c:
  c.execute("INSERT INTO wrong_question_states(question_id,project_id,state,wrong_count,correct_after_error_count,updated_at) VALUES (?,?,'review_due',2,0,1)",(q['id'],p['id']))
 svc=LearningRecommendationService(r); items=svc.generate(project_id=p['id'],trigger='time_budget',time_budget_text='今天只有10分钟')
 assert {x['recommendation_type'] for x in items}>={'review_proposal','similar_question_suggestion','practice_proposal'}
 target=next(x for x in items if x['recommendation_type']=='practice_proposal'); decided=svc.decide(recommendation_id=target['id'],action='edited_accepted',payload={'limit':5})
 assert decided['actions'][0]['action']=='edited_accepted'
 with r._connect() as c: assert c.execute('SELECT COUNT(*) FROM practice_sessions').fetchone()[0]==0



def test_accept_recommendation_returns_next_action(tmp_path: Path) -> None:
    from deeptutor.services.learning_center import LearningCenterRepository
    from deeptutor.services.learning_center.recommendations import LearningRecommendationService
    from deeptutor.services.learning_center.practice import LearningPracticeService
    from tests.services.learning_center.test_practice import _seed
    repo = LearningCenterRepository(tmp_path / "learning_center.db")
    ids = _seed(repo)
    practice = LearningPracticeService(repo)
    session = practice.start(project_id=ids["project"], mode="learning", limit=1, question_ids=[ids["first"]])
    item = session["questions"][0]
    practice.submit(session["id"], [{"id": item["id"], "user_answer": "Z", "confidence": "sure"}], finish=True)
    service = LearningRecommendationService(repo)
    items = service.generate(project_id=ids["project"], trigger="requested")
    assert items
    decided = service.decide(recommendation_id=items[0]["id"], action="accepted")
    assert decided.get("next_action")
    assert decided["next_action"]["type"] == "open_practice"
    assert decided["next_action"]["query"]["project_id"] == ids["project"]
