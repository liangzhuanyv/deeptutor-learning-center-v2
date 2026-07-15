from __future__ import annotations
import json
from pathlib import Path
from deeptutor.services.learning_center import LearningCenterRepository
from deeptutor.services.learning_center.imports import LearningImportRequest, LearningImportService


def _payload() -> LearningImportRequest:
    fixture = Path(__file__).parents[2] / "fixtures" / "learning_center" / "canonical_import_v1.json"
    return LearningImportRequest.model_validate(json.loads(fixture.read_text()))


def test_analyze_preview_approve_commit_and_rollback_non_financial_import(tmp_path: Path) -> None:
    repo=LearningCenterRepository(tmp_path/'learning_center.db')
    service=LearningImportService(repo)
    batch=service.analyze(_payload())
    assert batch['status']=='preview_ready'
    assert batch['summary']['valid']==1
    assert batch['summary']['missing_answers']==1
    assert batch['events'][0]['stage']=='preview_ready'
    assert service.quality_report(batch['id'])['items'][1]['status']=='manual_review'
    mapped = service.update_mapping(batch['id'],{'module':'module_path'})
    assert mapped['events'][-1]['stage'] == 'mapping_updated'
    service.approve(batch['id'])
    committed=service.commit(batch['id'])
    assert committed['status']=='completed'
    assert committed['summary']['committed']==1
    assert committed['events'][-1]['stage']=='completed'
    question_id=[item['question_id'] for item in committed['items'] if item['status']=='committed'][0]
    assert repo.get_question(question_id)['source_answer']=='A'
    rolled=service.rollback(batch['id'])
    assert rolled['status']=='rolled_back'
    assert rolled['events'][-1]['stage']=='rolled_back'
    try:
        repo.get_question(question_id)
    except Exception:
        pass
    else:
        raise AssertionError('Rollback must remove only the batch-created question')
    assert repo.list_projects() == []


def test_exact_duplicate_is_previewed_without_commit(tmp_path: Path) -> None:
    repo=LearningCenterRepository(tmp_path/'learning_center.db'); service=LearningImportService(repo)
    request=_payload().model_copy(deep=True)
    request.items.append(request.items[0].model_copy(update={'external_id':'cell-1-copy'}))
    batch=service.analyze(request)
    assert batch['summary']['duplicates']==1
    assert [item['status'] for item in batch['items']].count('duplicate')==1

import asyncio


def test_ai_enrichment_is_structured_and_committed_as_provenance(tmp_path: Path) -> None:
    from deeptutor.services.exam_enrichment.models import EnrichmentPayload

    class FakeClient:
        calls = 0

        def resolved_provider_and_model(self) -> tuple[str, str]:
            return ('fake-provider', 'fake-model')

        async def enrich(self, _prompt: str) -> EnrichmentPayload:
            FakeClient.calls += 1
            return EnrichmentPayload(
                suggested_answer='A',
                answer_confidence=0.92,
                explanation='A perfect fifth spans seven semitones.',
            )

    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    service = LearningImportService(
        repo,
        enrichment_client_factory=lambda **_kwargs: FakeClient(),
    )
    batch = service.analyze(_payload())
    enriched = asyncio.run(service.enrich(batch['id'], prompt_version='test-import/v1'))
    suggestion = enriched['items'][0]['quality']['ai_suggestions'][0]
    assert suggestion['provider'] == 'fake-provider'
    assert suggestion['model'] == 'fake-model'
    assert suggestion['prompt_version'] == 'test-import/v1'
    assert enriched['summary']['ai_classified_items'] == 2
    assert enriched['summary']['ai_rate_limit_per_minute'] == 60
    resumed = asyncio.run(service.enrich(batch['id'], rate_limit_per_minute=600))
    assert resumed['summary']['ai_enrichment_processed'] == 0
    assert resumed['summary']['ai_enrichment_skipped'] == 2
    assert FakeClient.calls == 2
    assert resumed['events'][-1]['stage'] == 'enrichment_completed'

    service.approve(batch['id'])
    committed = service.commit(batch['id'])
    question_id = next(item['question_id'] for item in committed['items'] if item['status'] == 'committed')
    provenance = repo.get_question_provenance(question_id)
    derivation = provenance['ai_derivations'][0]
    assert derivation['provider'] == 'fake-provider'
    assert derivation['model'] == 'fake-model'
    assert derivation['prompt_version'] == 'test-import/v1'
    assert derivation['output']['text'] == 'A perfect fifth spans seven semitones.'


def test_commit_is_resumable_and_invalid_state_transitions_are_rejected(tmp_path: Path) -> None:
    from deeptutor.services.learning_center.imports.service import ImportBatchStateError

    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    service = LearningImportService(repo)
    batch = service.analyze(_payload())
    try:
        service.commit(batch['id'])
    except ImportBatchStateError:
        pass
    else:
        raise AssertionError('Commit must require explicit approval')
    service.approve(batch['id'])
    first = service.commit(batch['id'])
    second = service.commit(batch['id'])
    assert second['summary']['committed'] == first['summary']['committed'] == 1
    assert len(repo.list_projects()) == 1
    assert second['events'][-1]['stage'] == 'completed'


def test_interrupted_commit_resumes_without_duplicate_source_or_question(tmp_path: Path, monkeypatch) -> None:
    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    service = LearningImportService(repo)
    request = _payload().model_copy(deep=True)
    request.items[1] = request.items[0].model_copy(
        update={'external_id': 'cell-3', 'stem': 'Which organelle makes proteins?'}
    )
    batch = service.analyze(request)
    service.approve(batch['id'])

    original_create_question = repo.create_question
    calls = 0

    def interrupted_create_question(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('simulated process interruption')
        return original_create_question(**kwargs)

    monkeypatch.setattr(repo, 'create_question', interrupted_create_question)
    try:
        service.commit(batch['id'])
    except RuntimeError as exc:
        assert 'interruption' in str(exc)
    else:
        raise AssertionError('The first commit should be interrupted')

    interrupted = service.get_batch(batch['id'])
    assert interrupted['status'] == 'committing'
    assert [item['status'] for item in interrupted['items']].count('committed') == 1
    assert interrupted['summary']['committed'] == 1
    assert interrupted['events'][-1]['stage'] == 'commit_progress'
    monkeypatch.setattr(repo, 'create_question', original_create_question)

    completed = service.commit(batch['id'])
    assert completed['status'] == 'completed'
    assert completed['summary']['committed'] == 2
    with repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM content_sources WHERE locator=?", (f"import-batch:{batch['id']}",)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions WHERE source_id=?", (completed['summary']['source_id'],)).fetchone()[0] == 2


def test_import_contract_and_quality_checks_are_strict(tmp_path: Path) -> None:
    from pydantic import ValidationError

    invalid = _payload().model_dump()
    invalid['unexpected'] = True
    try:
        LearningImportRequest.model_validate(invalid)
    except ValidationError:
        pass
    else:
        raise AssertionError('Unknown contract fields must be rejected')

    invalid_options = _payload().model_dump()
    invalid_options['items'][0]['options'] = {'A': 'Nucleus', ' A ': 'Duplicate after normalization'}
    try:
        LearningImportRequest.model_validate(invalid_options)
    except ValidationError:
        pass
    else:
        raise AssertionError('Normalized option-key collisions must be rejected')

    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    request = _payload().model_copy(deep=True)
    request.items[0] = request.items[0].model_copy(
        update={'module_path': [], 'knowledge_points': [], 'source_answer': 'Z'}
    )
    batch = LearningImportService(repo).analyze(request)
    issue_types = {issue['type'] for issue in batch['items'][0]['quality']['issues']}
    assert {'answer_not_in_options', 'missing_taxonomy'} <= issue_types
    assert batch['items'][0]['status'] == 'manual_review'


def test_near_duplicate_candidate_is_flagged_for_manual_review(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    request = _payload().model_copy(deep=True)
    request.items.append(
        request.items[0].model_copy(
            update={'external_id': 'cell-1-near', 'stem': 'Which organelle contains DNA!'}
        )
    )
    batch = LearningImportService(repo).analyze(request)
    near = next(item for item in batch['items'] if item['external_id'] == 'cell-1-near')
    assert near['status'] == 'manual_review'
    assert any(issue['type'] == 'near_duplicate' for issue in near['quality']['issues'])


def test_canonical_import_never_reads_paths_or_urls_from_source_metadata(tmp_path: Path, monkeypatch) -> None:
    import builtins

    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    request = _payload().model_copy(deep=True)
    request.bank.source = {
        'path': '../../exam_practice.db',
        'url': 'file:///etc/passwd',
        'archive': '../../payload.zip',
    }

    def fail_open(*_args, **_kwargs):
        raise AssertionError('Canonical JSON analysis must not open a path supplied in source metadata')

    monkeypatch.setattr(builtins, 'open', fail_open)
    batch = LearningImportService(repo).analyze(request)
    assert batch['configuration']['request']['bank']['source']['url'] == 'file:///etc/passwd'


def test_approval_selection_limits_committed_items(tmp_path: Path) -> None:
    repo = LearningCenterRepository(tmp_path / 'learning_center.db')
    service = LearningImportService(repo)
    request = _payload().model_copy(deep=True)
    request.items[1] = request.items[0].model_copy(
        update={'external_id': 'cell-3', 'stem': 'Which organelle makes proteins?'}
    )
    batch = service.analyze(request)
    service.approve(batch['id'], mode='selected', selected_item_ids=[batch['items'][1]['id']])
    committed = service.commit(batch['id'])
    assert committed['summary']['approved'] == 1
    assert committed['summary']['committed'] == 1
    assert [item['status'] for item in committed['items']].count('committed') == 1
