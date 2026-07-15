from __future__ import annotations
from pathlib import Path
from deeptutor.services.learning_center import LearningCenterRepository
from deeptutor.services.learning_center.mastery import LearningMasteryService
from deeptutor.services.learning_center.practice import LearningPracticeService


def _question(repo: LearningCenterRepository) -> tuple[str, str]:
    p=repo.create_project(name='Mastery',kind='course'); s=repo.create_content_source(project_id=p['id'],source_type='fixture'); b=repo.create_bank(project_id=p['id'],source_id=s['id'],name='Bank'); v=repo.create_bank_version(bank_id=b['id'],source_id=s['id'],version='v1'); m=repo.create_module(project_id=p['id'],name='M',path='m'); kp=repo.create_knowledge_point(project_id=p['id'],module_id=m['id'],name='KP'); q=repo.create_question(project_id=p['id'],bank_id=b['id'],bank_version_id=v['id'],module_id=m['id'],source_id=s['id'],stem='Q?',options={'A':'yes','B':'no'},source_answer='A',knowledge_point_ids=[kp['id']]); return p['id'],q['id']


def test_manual_mastery_survives_later_error_and_reopen_is_advisory(tmp_path: Path) -> None:
    repo=LearningCenterRepository(tmp_path/'lc.db'); project_id, question_id=_question(repo); practice=LearningPracticeService(repo); mastery=LearningMasteryService(repo)
    session=practice.start(project_id=project_id,mode='learning',limit=1); item=session['questions'][0]
    practice.submit(session['id'], [{'id':item['id'],'user_answer':'B','confidence':'sure'}])
    assert mastery.question_detail(question_id)['wrong_state']['state']=='review_due'
    detail=mastery.set_question_override(question_id=question_id,mastered=True,note='I can explain it')
    assert detail['wrong_state']['state']=='manual_mastered'
    session2=practice.start(project_id=project_id,mode='learning',limit=1); item2=session2['questions'][0]
    practice.submit(session2['id'], [{'id':item2['id'],'user_answer':'B','confidence':'guess'}])
    detail=mastery.question_detail(question_id)
    assert detail['wrong_state']['state']=='reopen_suggested'
    assert detail['manual_override']['status']=='mastered'
    assert detail['mastery']['algorithm_version']=='mastery-v1'
    assert detail['evidence']
    assert mastery.review_queue(project_id=project_id,filter='reopen')[0]['question_id']==question_id
    assert mastery.recalculate(project_id=project_id,dry_run=True)['question_count']==1
