"""Auditable canonical JSON import batches.  No LLM writes SQLite directly."""
from __future__ import annotations
import asyncio, json, sqlite3, time, uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from ..normalization import canonical_json, clean_text, question_fingerprint
from ..repository import LearningCenterRepository
from .contracts import LearningImportRequest

class ImportBatchNotFoundError(Exception): pass
class ImportBatchStateError(Exception): pass

def _load(v: str, fallback: Any):
    try:
        x=json.loads(v)
        return x if isinstance(x,type(fallback)) else fallback
    except Exception: return fallback

def _now(): return time.time()
def _id(prefix: str): return f'{prefix}_{uuid.uuid4().hex}'

class LearningImportService:
    def __init__(self, repository: LearningCenterRepository | None = None, *, enrichment_client_factory: Any | None = None):
        self.repository=repository or LearningCenterRepository()
        self._enrichment_client_factory=enrichment_client_factory
    def _connect(self): return self.repository._connect()  # controlled service-owned storage boundary
    def _event(self, conn, batch_id: str, stage: str, message: str, payload: dict[str, Any] | None = None) -> None:
        conn.execute("INSERT INTO import_batch_events (id,batch_id,stage,message,payload_json,created_at) VALUES (?,?,?,?,?,?)", (_id('import_event'), batch_id, stage, message, canonical_json(payload or {}), _now()))

    def _batch(self, conn, batch_id):
        row=conn.execute('SELECT * FROM import_batches WHERE id=?',(batch_id,)).fetchone()
        if row is None: raise ImportBatchNotFoundError(f'Import batch not found: {batch_id}')
        return row
    def _summary(self, items: list[dict[str, Any]]) -> dict[str, int]:
        statuses=[i['status'] for i in items]
        issue_types=[issue['type'] for i in items for issue in i['quality']['issues']]
        return {'discovered':len(items),'valid':statuses.count('valid'),'skipped':statuses.count('duplicate'),'duplicates':statuses.count('duplicate'),'missing_answers':issue_types.count('missing_answer'),'missing_explanations':issue_types.count('missing_explanation'),'ai_classified_items':0,'low_confidence_items':0,'manual_review_items':sum(i['status']=='manual_review' for i in items)}
    def analyze(self, request: LearningImportRequest) -> dict[str, Any]:
        batch_id=_id('import_batch'); now=_now(); seen: dict[str,str]={}; prepared=[]
        for ordinal,item in enumerate(request.items):
            options={clean_text(k):clean_text(v) for k,v in item.options.items()}
            raw_answer=clean_text(item.source_answer).upper()
            answer=raw_answer.replace(',','').replace(' ','')
            answer_parts=[part for part in raw_answer.replace(';', ',').replace(' ', ',').split(',') if part]
            issues=[]
            if not answer:
                issues.append({'type':'missing_answer','severity':'error'})
            elif options and any(part not in options for part in answer_parts):
                issues.append({'type':'answer_not_in_options','severity':'error'})
            if item.question_type in {'single_choice','multiple_choice','true_false'} and not options:
                issues.append({'type':'missing_options','severity':'error'})
            if item.question_type == 'single_choice' and len(answer_parts) > 1:
                issues.append({'type':'single_choice_multiple_answers','severity':'error'})
            if not clean_text(item.source_explanation):
                issues.append({'type':'missing_explanation','severity':'warning'})
            if not item.module_path and not item.knowledge_points:
                issues.append({'type':'missing_taxonomy','severity':'warning'})
            imported_text=[item.stem, item.source_answer, item.source_explanation, *item.options.keys(), *item.options.values()]
            if any('\ufffd' in value or '\x00' in value for value in imported_text):
                issues.append({'type':'encoding_suspected','severity':'error'})
            if (len(item.stem) >= 19_950 or len(item.source_answer) >= 9_950 or
                    len(item.source_explanation) >= 49_950):
                issues.append({'type':'possible_truncation','severity':'warning'})
            fp=question_fingerprint(item.stem,options,answer)
            status='valid'
            if fp in seen:
                issues.append({'type':'exact_duplicate','severity':'error','duplicate_of':seen[fp]}); status='duplicate'
            else: seen[fp]=item.external_id
            if status == 'valid' and any(
                issue['severity'] == 'error' or issue['type'] in {'missing_taxonomy', 'possible_truncation'}
                for issue in issues
            ):
                status = 'manual_review'
            # bounded near-duplicate check keeps preview deterministic for normal import sizes.
            for existing in prepared[-200:]:
                if status=='valid' and SequenceMatcher(None, clean_text(item.stem), clean_text(existing['normalized']['stem'])).ratio()>=0.96:
                    issues.append({'type':'near_duplicate','severity':'warning','duplicate_of':existing['external_id']}); status='manual_review'; break
            normalized={'external_id':item.external_id,'module_path':[clean_text(v) for v in item.module_path if clean_text(v)],'knowledge_points':[clean_text(v) for v in item.knowledge_points if clean_text(v)],'question_type':item.question_type,'stem':clean_text(item.stem),'options':options,'source_answer':answer,'source_explanation':clean_text(item.source_explanation),'metadata':item.metadata,'fingerprint':fp}
            prepared.append({'id':_id('import_item'),'external_id':item.external_id,'ordinal':ordinal,'status':status,'raw':item.model_dump(),'normalized':normalized,'quality':{'issues':issues}})
        summary=self._summary(prepared)
        config={'request':request.model_dump(),'mapping':{},'protocol':'learning-import/v1'}
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute("INSERT INTO import_batches (id,project_id,source_id,schema_version,status,configuration_json,summary_json,created_at,updated_at,completed_at) VALUES (?,?,NULL,'learning-import/v1','preview_ready',?,?,?, ?,NULL)",(batch_id,None,canonical_json(config),canonical_json(summary),now,now))
                for item in prepared:
                    conn.execute("INSERT INTO import_items (id,batch_id,external_id,ordinal,status,raw_json,normalized_json,quality_json,question_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,NULL,?,?)",(item['id'],batch_id,item['external_id'],item['ordinal'],item['status'],canonical_json(item['raw']),canonical_json(item['normalized']),canonical_json(item['quality']),now,now))
                self._event(conn, batch_id, 'preview_ready', 'Canonical payload analyzed', summary)
                conn.commit()
            except Exception: conn.rollback(); raise
        return self.get_batch(batch_id)
    async def enrich(self, batch_id: str, *, profile_id: str | None = None, provider: str | None = None, model: str | None = None, prompt_version: str = 'learning-import/v1', limit: int = 100, rate_limit_per_minute: int = 60) -> dict[str, Any]:
        from deeptutor.services.exam_enrichment.client import ExamEnrichmentClient
        batch = self.get_batch(batch_id)
        if batch['status'] not in {'preview_ready', 'approved'}:
            raise ImportBatchStateError('Only preview-ready or approved imports can be enriched')
        client = (self._enrichment_client_factory(profile_id=profile_id, provider=provider, model=model) if self._enrichment_client_factory else ExamEnrichmentClient(profile_id=profile_id, provider=provider, model=model))
        resolved_provider, resolved_model = client.resolved_provider_and_model()
        with self._connect() as conn:
            self._event(conn, batch_id, 'enrichment_started', 'AI enrichment started', {
                'provider': resolved_provider, 'model': resolved_model,
                'prompt_version': prompt_version, 'limit': limit,
                'rate_limit_per_minute': rate_limit_per_minute,
            })
        processed = 0; failed = 0; skipped = 0
        minimum_interval = 60 / rate_limit_per_minute
        for item in batch['items']:
            if processed >= limit or item['status'] not in {'valid', 'manual_review'}: continue
            if item['quality'].get('ai_suggestions'):
                skipped += 1
                continue
            if processed:
                await asyncio.sleep(minimum_interval)
            n=item['normalized']
            prompt = json.dumps({'stem':n['stem'],'options':n['options'],'source_answer':n['source_answer'],'source_explanation':n['source_explanation']}, ensure_ascii=False)
            try:
                result=await client.enrich(prompt)
                quality=item['quality']; quality.setdefault('ai_suggestions',[]).append({'suggested_answer':result.suggested_answer,'answer_confidence':result.answer_confidence,'explanation':result.explanation,'provider':resolved_provider,'model':resolved_model,'prompt_version':prompt_version,'generated_at':datetime.now(timezone.utc).isoformat(),'review_status':'unreviewed'})
                if result.suggested_answer and n['source_answer'] and result.suggested_answer != n['source_answer']:
                    quality.setdefault('issues', []).append({'type':'source_ai_answer_conflict','severity':'warning','source_answer':n['source_answer'],'suggested_answer':result.suggested_answer})
                if result.answer_confidence is not None and result.answer_confidence < 0.7:
                    quality.setdefault('issues', []).append({'type':'low_ai_confidence','severity':'warning','confidence':result.answer_confidence})
                with self._connect() as conn:
                    conn.execute('UPDATE import_items SET quality_json=?,updated_at=? WHERE id=?',(canonical_json(quality),_now(),item['id']))
                processed += 1
            except Exception as exc:
                failed += 1
                quality=item['quality']; quality.setdefault('issues',[]).append({'type':'ai_enrichment_failed','severity':'warning','message':str(exc)[:500]})
                with self._connect() as conn: conn.execute('UPDATE import_items SET quality_json=?,updated_at=? WHERE id=?',(canonical_json(quality),_now(),item['id']))
        with self._connect() as conn:
            b=self._batch(conn,batch_id)
            refreshed=self._items(conn,batch_id)
            summary=_load(b['summary_json'],{})
            issue_types=[issue.get('type') for item in refreshed for issue in item['quality'].get('issues', [])]
            summary.update({'ai_classified_items':sum(bool(item['quality'].get('ai_suggestions')) for item in refreshed),'ai_enrichment_processed':processed,'ai_enrichment_skipped':skipped,'ai_enrichment_failed':failed,'ai_provider':resolved_provider,'ai_model':resolved_model,'ai_rate_limit_per_minute':rate_limit_per_minute,'low_confidence_items':issue_types.count('low_ai_confidence'),'conflict_suspicions':issue_types.count('source_ai_answer_conflict')})
            conn.execute('UPDATE import_batches SET summary_json=?,updated_at=? WHERE id=?',(canonical_json(summary),_now(),batch_id))
            self._event(conn, batch_id, 'enrichment_completed', 'AI enrichment completed', {
                'processed': processed, 'skipped': skipped, 'failed': failed,
                'provider': resolved_provider, 'model': resolved_model,
            })
        return self.get_batch(batch_id)

    def get_batch(self,batch_id:str)->dict[str,Any]:
        with self._connect() as conn:
            b=self._batch(conn,batch_id); items=self._items(conn,batch_id)
            result=self._serialize_batch(b,items)
            result['events']=[{'stage':e['stage'],'message':e['message'],'payload':_load(e['payload_json'],{}),'created_at':e['created_at']} for e in conn.execute('SELECT * FROM import_batch_events WHERE batch_id=? ORDER BY created_at',(batch_id,))]
            return result
    def _items(self,conn,batch_id):
        return [{'id':r['id'],'external_id':r['external_id'],'ordinal':r['ordinal'],'status':r['status'],'raw':_load(r['raw_json'],{}),'normalized':_load(r['normalized_json'],{}),'quality':_load(r['quality_json'],{}),'question_id':r['question_id']} for r in conn.execute('SELECT * FROM import_items WHERE batch_id=? ORDER BY ordinal',(batch_id,))]
    def _serialize_batch(self,row,items):
        return {'id':row['id'],'project_id':row['project_id'],'schema_version':row['schema_version'],'status':row['status'],'configuration':_load(row['configuration_json'],{}),'summary':_load(row['summary_json'],{}),'items':items,'created_at':row['created_at'],'updated_at':row['updated_at'],'completed_at':row['completed_at']}
    def preview(self,batch_id): return self.get_batch(batch_id)
    def quality_report(self,batch_id):
        b=self.get_batch(batch_id); return {'batch_id':batch_id,'status':b['status'],'summary':b['summary'],'items':[{'id':i['id'],'external_id':i['external_id'],'status':i['status'],'quality':i['quality']} for i in b['items']]}
    def update_mapping(self,batch_id,mapping:dict[str,Any]):
        with self._connect() as conn:
            b=self._batch(conn,batch_id)
            if b['status'] not in {'created','preview_ready'}: raise ImportBatchStateError('Mapping can only be changed before approval')
            cfg=_load(b['configuration_json'],{}); cfg['mapping']=mapping; now=_now()
            conn.execute("UPDATE import_batches SET configuration_json=?,updated_at=? WHERE id=?",(canonical_json(cfg),now,batch_id))
            self._event(conn,batch_id,'mapping_updated','Import field mapping updated',mapping)
        return self.get_batch(batch_id)
    def approve(self, batch_id: str, *, mode: str = 'all_valid', selected_item_ids: list[str] | None = None, minimum_confidence: float = 0.8) -> dict[str, Any]:
        selected_item_ids = selected_item_ids or []
        with self._connect() as conn:
            batch = self._batch(conn, batch_id)
            if batch['status'] != 'preview_ready':
                raise ImportBatchStateError('Only preview-ready imports can be approved')
            items = self._items(conn, batch_id)
            valid_items = [item for item in items if item['status'] == 'valid']
            if mode == 'all_valid':
                approved_ids = [item['id'] for item in valid_items]
            elif mode == 'selected':
                requested = set(selected_item_ids)
                approved_ids = [item['id'] for item in valid_items if item['id'] in requested]
                if not approved_ids:
                    raise ImportBatchStateError('Selected approval requires at least one valid import item')
            elif mode == 'high_confidence':
                approved_ids = []
                for item in valid_items:
                    suggestions = item['quality'].get('ai_suggestions', [])
                    confidence = suggestions[-1].get('answer_confidence') if suggestions else 1.0
                    if confidence is not None and float(confidence) >= minimum_confidence:
                        approved_ids.append(item['id'])
                if not approved_ids:
                    raise ImportBatchStateError('No valid items meet the requested confidence threshold')
            else:
                raise ImportBatchStateError(f'Unknown approval mode: {mode}')
            config = _load(batch['configuration_json'], {})
            config['approval'] = {
                'mode': mode, 'item_ids': approved_ids,
                'minimum_confidence': minimum_confidence,
            }
            summary = _load(batch['summary_json'], {})
            summary['approved'] = len(approved_ids)
            now = _now()
            conn.execute(
                "UPDATE import_batches SET status='approved',configuration_json=?,summary_json=?,updated_at=? WHERE id=?",
                (canonical_json(config), canonical_json(summary), now, batch_id),
            )
            self._event(conn, batch_id, 'approved', 'Import approved', config['approval'])
        return self.get_batch(batch_id)

    def cancel(self,batch_id):
        with self._connect() as conn:
            b=self._batch(conn,batch_id)
            if b['status'] in {'completed','rolled_back'}: raise ImportBatchStateError('Committed imports must use rollback')
            conn.execute("UPDATE import_batches SET status='cancelled',updated_at=? WHERE id=?",(_now(),batch_id)); self._event(conn,batch_id,'cancelled','Import cancelled'); return self.get_batch(batch_id)
    def commit(self, batch_id: str) -> dict[str, Any]:
        """Commit an approved batch with durable per-item resume checkpoints.

        Repository methods deliberately use their own short SQLite transactions.
        Therefore each successfully persisted question is immediately recorded on
        its import item.  If a process stops between items, invoking ``commit``
        again continues from those checkpoints and reuses the batch source.
        """
        with self._connect() as conn:
            batch = self._batch(conn, batch_id)
            if batch['status'] == 'completed':
                return self.get_batch(batch_id)
            if batch['status'] not in {'approved', 'committing'}:
                raise ImportBatchStateError('Only approved or interrupted imports can be committed')
            config = _load(batch['configuration_json'], {})
            request = LearningImportRequest.model_validate(config['request'])
            approved_item_ids = set(config.get('approval', {}).get('item_ids', []))
            if batch['status'] == 'approved':
                conn.execute(
                    "UPDATE import_batches SET status='committing',updated_at=? WHERE id=?",
                    (_now(), batch_id),
                )
                self._event(conn, batch_id, 'committing', 'Approved import commit started')

        with self._connect() as conn:
            existing = conn.execute(
                'SELECT id FROM learning_projects WHERE external_id=?',
                (request.project.external_id,),
            ).fetchone()
        project = (
            self.repository.get_project(existing['id'])
            if existing
            else self.repository.create_project(
                name=request.project.name,
                kind=request.project.kind,
                external_id=request.project.external_id,
                metadata=request.project.metadata,
            )
        )

        source_locator = f'import-batch:{batch_id}'
        with self._connect() as conn:
            source_row = conn.execute(
                'SELECT * FROM content_sources WHERE project_id=? AND locator=? ORDER BY created_at LIMIT 1',
                (project['id'], source_locator),
            ).fetchone()
        source = (
            self.repository._serialize_source(source_row)
            if source_row
            else self.repository.create_content_source(
                project_id=project['id'], source_type='canonical_json', locator=source_locator,
                external_id=request.bank.external_id, revision=request.bank.version,
                metadata=request.bank.source,
            )
        )

        with self._connect() as conn:
            existing_bank = conn.execute(
                'SELECT * FROM question_banks WHERE project_id=? AND external_id=?',
                (project['id'], request.bank.external_id),
            ).fetchone()
        bank = (
            self.repository._serialize_bank(existing_bank)
            if existing_bank
            else self.repository.create_bank(
                project_id=project['id'], source_id=source['id'],
                external_id=request.bank.external_id, name=request.bank.name,
            )
        )
        with self._connect() as conn:
            existing_version = conn.execute(
                'SELECT * FROM question_bank_versions WHERE bank_id=? AND version=?',
                (bank['id'], request.bank.version),
            ).fetchone()
        version = (
            self.repository._serialize_bank_version(existing_version)
            if existing_version
            else self.repository.create_bank_version(
                bank_id=bank['id'], source_id=source['id'], version=request.bank.version,
            )
        )

        # Persist ownership as soon as it is known so a later rollback can also
        # clean up a partially committed batch without touching unrelated data.
        with self._connect() as conn:
            current = self._batch(conn, batch_id)
            summary = _load(current['summary_json'], {})
            summary.update({
                'project_id': project['id'], 'source_id': source['id'],
                'bank_id': bank['id'], 'bank_version_id': version['id'],
            })
            conn.execute(
                'UPDATE import_batches SET project_id=?,source_id=?,summary_json=?,updated_at=? WHERE id=?',
                (project['id'], source['id'], canonical_json(summary), _now(), batch_id),
            )

        modules: dict[tuple[str, ...], str] = {}
        committed = 0
        resumable_items = self.get_batch(batch_id)['items']
        total_committable = sum(item['status'] in {'valid', 'committed'} for item in resumable_items)
        for item in resumable_items:
            if item['status'] == 'committed':
                committed += 1
                continue
            if item['status'] != 'valid' or item['id'] not in approved_item_ids:
                continue
            normalized = item['normalized']
            parent_id: str | None = None
            parts: list[str] = []
            for part in normalized['module_path']:
                parts.append(part)
                path = '/'.join(parts)
                key = tuple(parts)
                if key not in modules:
                    with self._connect() as conn:
                        row = conn.execute(
                            'SELECT id FROM content_modules WHERE project_id=? AND path=?',
                            (project['id'], path),
                        ).fetchone()
                    module = (
                        {'id': row['id']}
                        if row
                        else self.repository.create_module(
                            project_id=project['id'], name=part, path=path,
                            parent_id=parent_id, external_id='import:' + path,
                        )
                    )
                    modules[key] = module['id']
                parent_id = modules[key]

            with self._connect() as conn:
                existing_question = conn.execute(
                    'SELECT id FROM questions WHERE source_id=? AND external_id=? ORDER BY created_at LIMIT 1',
                    (source['id'], normalized['external_id']),
                ).fetchone()
            created_now = existing_question is None
            question = (
                self.repository.get_question(existing_question['id'])
                if existing_question
                else self.repository.create_question(
                    project_id=project['id'], bank_id=bank['id'], bank_version_id=version['id'],
                    module_id=parent_id, source_id=source['id'], external_id=normalized['external_id'],
                    fingerprint=normalized['fingerprint'], question_type=normalized['question_type'],
                    stem=normalized['stem'], options=normalized['options'],
                    source_answer=normalized['source_answer'],
                    source_explanation=normalized['source_explanation'], metadata=normalized['metadata'],
                )
            )
            if created_now:
                # Preview-stage AI suggestions become separately-labelled provenance
                # only after explicit approval. Source fields remain immutable.
                for suggestion in item['quality'].get('ai_suggestions', []):
                    revision = self.repository.add_content_revision(
                        project_id=project['id'], question_id=question['id'], field_name='explanation',
                        value={'text': suggestion.get('explanation', '')},
                        provenance_type='ai_generated', review_status='unreviewed',
                    )
                    self.repository.add_ai_derivation(
                        project_id=project['id'], question_id=question['id'], revision_id=revision['id'],
                        derivation_type='explanation', output={'text': suggestion.get('explanation', '')},
                        provider=str(suggestion.get('provider') or 'configured'),
                        model=str(suggestion.get('model') or 'configured'),
                        prompt_version=str(suggestion.get('prompt_version') or 'learning-import/v1'),
                        input_references=[source_locator, item['id']],
                        confidence=suggestion.get('answer_confidence'), review_status='unreviewed',
                    )
            committed += 1
            with self._connect() as conn:
                conn.execute(
                    "UPDATE import_items SET status='committed',question_id=?,updated_at=? WHERE id=?",
                    (question['id'], _now(), item['id']),
                )
                progress_summary = _load(self._batch(conn, batch_id)['summary_json'], {})
                progress_summary['committed'] = committed
                progress_summary['commit_total'] = total_committable
                conn.execute(
                    'UPDATE import_batches SET summary_json=?,updated_at=? WHERE id=?',
                    (canonical_json(progress_summary), _now(), batch_id),
                )
                if committed == 1 or committed == total_committable or committed % 25 == 0:
                    self._event(conn, batch_id, 'commit_progress', 'Import commit progress', {
                        'committed': committed, 'total': total_committable,
                    })

        with self._connect() as conn:
            summary = _load(self._batch(conn, batch_id)['summary_json'], {})
            summary['committed'] = committed
            now = _now()
            conn.execute(
                "UPDATE import_batches SET status='completed',summary_json=?,updated_at=?,completed_at=? WHERE id=?",
                (canonical_json(summary), now, now, batch_id),
            )
            self._event(conn, batch_id, 'completed', 'Approved import committed', summary)
        return self.get_batch(batch_id)

    def rollback(self,batch_id):
        with self._connect() as conn:
            b=self._batch(conn,batch_id)
            if b['status'] not in {'completed','committing'}: raise ImportBatchStateError('Only completed or interrupted imports can be rolled back')
            ids=[r[0] for r in conn.execute('SELECT question_id FROM import_items WHERE batch_id=? AND question_id IS NOT NULL',(batch_id,))]
            conn.execute('BEGIN IMMEDIATE')
            try:
                if ids: conn.execute('DELETE FROM questions WHERE id IN ('+','.join('?' for _ in ids)+')',ids)
                summary=_load(b['summary_json'],{})
                version_id=summary.get('bank_version_id'); bank_id=summary.get('bank_id'); project_id=summary.get('project_id'); source_id=summary.get('source_id')
                if version_id and conn.execute('SELECT COUNT(*) FROM questions WHERE bank_version_id=?',(version_id,)).fetchone()[0] == 0:
                    conn.execute('DELETE FROM question_bank_versions WHERE id=?',(version_id,))
                if bank_id and conn.execute('SELECT COUNT(*) FROM question_bank_versions WHERE bank_id=?',(bank_id,)).fetchone()[0] == 0:
                    conn.execute('DELETE FROM question_banks WHERE id=?',(bank_id,))
                if project_id and conn.execute('SELECT COUNT(*) FROM question_banks WHERE project_id=?',(project_id,)).fetchone()[0] == 0:
                    conn.execute('DELETE FROM learning_projects WHERE id=?',(project_id,))
                if source_id and conn.execute('SELECT COUNT(*) FROM questions WHERE source_id=?',(source_id,)).fetchone()[0] == 0:
                    conn.execute('DELETE FROM content_sources WHERE id=?',(source_id,))
                conn.execute("UPDATE import_batches SET status='rolled_back',updated_at=? WHERE id=?",(_now(),batch_id)); self._event(conn,batch_id,'rolled_back','Committed questions removed from this batch'); conn.commit()
            except Exception: conn.rollback(); raise
        return self.get_batch(batch_id)
